"""DPC LR2 numerical correctness and deterministic lost-update experiment."""
import json
import math
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, "/srv" if Path("/srv/app").exists() else str(Path(__file__).resolve().parents[1] / "dpc" / "api"))
from app.numerics import partial, reference, split  # noqa: E402


def update(shared, barrier, lock, value, mode):
    if mode == "unsafe":
        previous = shared.value
        barrier.wait(timeout=10)
        shared.value = previous + value
    else:
        with lock:
            shared.value += value


def shared_sum(values, mode):
    ctx = mp.get_context("spawn")
    shared = ctx.Value("d", 0.0, lock=False)
    barrier = ctx.Barrier(len(values))
    lock = ctx.Lock()
    processes = [ctx.Process(target=update, args=(shared, barrier, lock, v, mode)) for v in values]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0, process.exitcode
    return shared.value


def main():
    a, b, n, workers = 0.0, 90.0, 10_000, 4
    ranges = split(n, workers)
    assert ranges[0][0] == 0 and ranges[-1][1] == n
    assert all(ranges[i][1] == ranges[i + 1][0] for i in range(workers - 1))
    values = [partial(a, (b - a) / n, lo, hi, "simpson") for lo, hi in ranges]
    target = reference(a, b)
    outcomes = {"unsafe": shared_sum(values, "unsafe"),
                "locked": shared_sum(values, "locked"),
                "local": math.fsum(values), "reference": target}
    tolerance = 0.01
    assert abs(outcomes["locked"] - target) < tolerance, outcomes
    assert abs(outcomes["local"] - target) < tolerance, outcomes
    assert abs(outcomes["unsafe"] - target) > tolerance, outcomes
    print(json.dumps(outcomes))


if __name__ == "__main__":
    main()
