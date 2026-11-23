"""Ray tasks validate tickets and call the API receiver; they never mutate sectors."""

import httpx
import psycopg
import ray
from psycopg.rows import dict_row

from . import config
from .faults import fault


@ray.remote(max_retries=2, retry_exceptions=False)
def scan_task(scan: dict) -> dict:
    if config.TICKET_CHECK_MODE == "fixture":
        import random
        import time

        time.sleep(random.uniform(config.TICKET_CHECK_MIN_MS, config.TICKET_CHECK_MAX_MS) / 1000)
        with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
            ticket = conn.execute(
                "SELECT t.id AS ticket_id, b.screening_id AS performance_id,"
                " (t.status='valid' AND b.status='confirmed') AS valid"
                " FROM tickets t JOIN bookings b ON b.id=t.booking_id WHERE t.code=%s",
                (scan["ticket_code"],),
            ).fetchone()
        result = ticket or {"ticket_id": scan["ticket_id"], "performance_id": "", "valid": False}
    else:
        with httpx.Client(timeout=config.TICKET_CHECK_TIMEOUT_S) as client:
            response = client.get(
                f"{config.WEB_API_URL.rstrip('/')}/v1/tickets/{scan['ticket_code']}",
                headers={"Authorization": f"Bearer {config.WEB_API_TOKEN}"},
            )
            if response.status_code == 404:
                result = {"ticket_id": scan["ticket_id"], "performance_id": "", "valid": False}
            else:
                response.raise_for_status()
                result = response.json()
    with httpx.Client(timeout=15) as client:
        accepted = client.post(
            f"{config.RECEIVER_URL.rstrip('/')}/internal/admission",
            json={"scan_id": scan["id"], "ticket": result},
            headers={"Authorization": f"Bearer {config.RECEIVER_TOKEN}"},
        )
        accepted.raise_for_status()
        decision = accepted.json()
    fault("after_effect_before_ack")
    return decision
