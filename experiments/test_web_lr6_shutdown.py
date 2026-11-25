import http.client
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = pathlib.Path(__file__).resolve().parent
APP_DIR = pathlib.Path("/srv") if pathlib.Path("/srv/app").is_dir() else HERE.parent / "web" / "server"
DATABASE_URL = os.environ["DATABASE_URL"]
PORT = int(os.environ.get("TEST_PORT", "18010"))
PAUSE_S = 4.0
DRAIN_DELAY_S = 2.0
passed = 0


def check(condition: bool, what: str) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL {what}")
    passed += 1
    print(f"ok   {what}")


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
    reply = conn.getresponse()
    data = reply.read()
    result = (reply.status, {k.lower(): v for k, v in reply.getheaders()}, json.loads(data) if data else None)
    conn.close()
    return result


def sql(text: str, params: tuple = ()) -> list:
    import psycopg

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(text, params) if params else conn.execute(text)
        return cur.fetchall() if cur.description else []


def main() -> None:
    sql((HERE / "web_lr2_reset.sql").read_text())
    faults = tempfile.mkdtemp()
    log_path = pathlib.Path(tempfile.mkdtemp()) / "app.log"
    env = {
        **os.environ,
        "FAULTS": "on",
        "FAULT_DIR": faults,
        "FAULT_PAUSE_S": str(PAUSE_S),
        "DRAIN_DELAY_S": str(DRAIN_DELAY_S),
        "DRAIN_TIMEOUT_S": "15",
        "INSTANCE": "shutdown-test",
    }
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT),
             "--no-access-log", "--timeout-graceful-shutdown", "25"],
            cwd=APP_DIR, env=env, stdout=log_file, stderr=subprocess.STDOUT,
        )
        try:
            run(proc, faults, log_path)
        finally:
            if proc.poll() is None:
                proc.kill()
    sql((HERE / "web_lr2_reset.sql").read_text())
    print(f"\n{passed} checks passed")


def run(proc: subprocess.Popen, faults: str, log_path: pathlib.Path) -> None:
    for _ in range(100):
        try:
            if call("GET", "/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.2)
    status, headers, body = call("GET", "/ready")
    check(status == 200 and body["status"] == "ready", "O6.3 before SIGTERM /ready answers 200")
    status, headers, body = call("POST", "/v1/auth/login", {"login": "alice@example.invalid", "password": "alice-pass"})
    cookie = {"Cookie": headers["set-cookie"].split(";")[0]}
    check(status == 200, "login works on the test instance")

    pathlib.Path(faults, "slow_request").touch()
    slow: dict = {}

    def slow_request() -> None:
        started = time.time()
        slow["reply"] = call("POST", "/v1/holds", {"category_id": "cat-race-50", "seats": 1},
                             {**cookie, "Idempotency-Key": uuid.uuid4().hex})
        slow["took"] = time.time() - started

    worker = threading.Thread(target=slow_request)
    worker.start()
    time.sleep(1.0)
    check(not pathlib.Path(faults, "slow_request").exists(), "the slow request has started (the pause was taken)")

    signalled = time.time()
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.5)

    status, headers, body = call("GET", "/ready")
    check(status == 503 and body["status"] == "draining" and "retry-after" in headers,
          "O6.3 after SIGTERM /ready -> 503 draining with Retry-After")
    status, _, body = call("GET", "/health")
    check(status == 200, "liveness /health still answers 200")
    status, headers, body = call("POST", "/v1/holds", {"category_id": "cat-race-50", "seats": 1},
                                 {**cookie, "Idempotency-Key": uuid.uuid4().hex})
    check(status == 503 and body["type"].endswith("shutting-down") and headers.get("retry-after") == "1"
          and headers.get("connection") == "close" and headers["content-type"].startswith("application/problem+json"),
          "O6.3 a new POST is refused with 503 shutting-down, Retry-After, Connection: close")
    status, _, body = call("GET", "/v1/me", headers=cookie)
    check(status == 503, "O6.3 a new GET of business data is refused as well")
    check(proc.poll() is None, "the process is still alive: the started request is not finished yet")

    worker.join(30)
    status, headers, body = slow["reply"]
    check(status == 201 and slow["took"] >= PAUSE_S - 0.5, "O6.3 the request that started before SIGTERM finished with 201")
    hold_id = body["id"]
    check(sql("SELECT status FROM bookings WHERE id = %s", (hold_id,)) == [("held",)],
          "O6.3 its result is committed in the database")

    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        raise AssertionError("FAIL the process did not stop within 30 s") from None
    stopped = time.time() - signalled
    check(proc.returncode in (0, -signal.SIGTERM), f"the process ended normally (code {proc.returncode})")
    check(DRAIN_DELAY_S <= stopped <= DRAIN_DELAY_S + PAUSE_S + 5, f"it stopped after {stopped:.1f} s: not at once, not hanging")
    text = log_path.read_text()
    check('"event": "shutdown.draining"' in text and '"event": "shutdown.stopping"' in text, "the log has shutdown.draining and shutdown.stopping")
    stopping = [json.loads(x) for x in text.splitlines() if '"shutdown.stopping"' in x][0]
    check(stopping["inflight"] == 0 and stopping["timed_out"] is False, "the process stopped only after the started work had finished")
    try:
        call("GET", "/health")
        refused = False
    except OSError:
        refused = True
    check(refused, "after the stop nothing listens on the port")


main()
