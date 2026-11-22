
"""Event handler for payment requests."""

import asyncio
import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from psycopg.types.json import Jsonb

from . import background, broker, config, db
from .faults import fault
from .jsonlog import log


HANDLER = "payment-worker"


def charge(operation: dict) -> dict:
    request = Request(
        f"{config.EXTERNAL_URL.rstrip('/')}/charge",
        data=json.dumps({
            "operation_id": operation["id"],
            "booking_id": operation["booking_id"],
            "amount_cents": operation["amount_cents"],
            "currency": operation["currency"],
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": operation["id"],
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 503:
            raise RuntimeError("payment provider temporarily unavailable") from exc
        raise

    if result.get("status") not in ("accepted", "rejected"):
        raise RuntimeError(f"unexpected payment response: {result}")

    return result


async def handle(record) -> None:
    event = json.loads(record.value)

    if event.get("type") != "payment.requested":
        return

    event_id = event["id"]
    operation_id = event["payload"]["operation_id"]

    async with db.connection() as conn:
        async with conn.transaction():
            cursor = await conn.execute(
                """
                SELECT o.id, o.booking_id, o.user_id, o.status,
                       o.amount_cents, o.currency,
                       b.status AS booking_status, b.hold_expires_at
                FROM operations o
                JOIN bookings b ON b.id = o.booking_id
                WHERE o.id = %s
                FOR UPDATE OF o
                """,
                (operation_id,),
            )
            operation = await cursor.fetchone()

            if operation is None:
                raise RuntimeError(
                    f"payment operation not found: {operation_id}"
                )

            cursor = await conn.execute(
                """
                SELECT 1
                FROM processed_messages
                WHERE handler = %s AND event_id = %s
                """,
                (HANDLER, event_id),
            )

            if await cursor.fetchone():
                return

            if operation["status"] in ("succeeded", "failed"):
                await conn.execute(
                    """
                    INSERT INTO processed_messages (handler, event_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (HANDLER, event_id),
                )
                return

            await conn.execute(
                """
                UPDATE operations
                SET status = 'running', updated_at = now()
                WHERE id = %s
                """,
                (operation_id,),
            )

    if (
        operation["status"] == "pending"
        and (
            operation["booking_status"] != "held"
            or operation["hold_expires_at"] <= datetime.now(timezone.utc)
        )
    ):
        result = {
            "status": "rejected",
            "reason": "hold_unavailable",
        }
    else:
        result = await asyncio.to_thread(charge, operation)
        fault("after_external_before_commit")


    async with db.connection() as conn:
        async with conn.transaction():
            cursor = await conn.execute(
                """
                SELECT status
                FROM operations
                WHERE id = %s
                FOR UPDATE
                """,
                (operation_id,),
            )
            current = await cursor.fetchone()

            if current["status"] in ("succeeded", "failed"):
                await conn.execute(
                    """
                    INSERT INTO processed_messages (handler, event_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (HANDLER, event_id),
                )
                return

            cursor = await conn.execute(
                """
                SELECT version
                FROM bookings
                WHERE id = %s
                FOR UPDATE
                """,
                (operation["booking_id"],),
            )
            booking = await cursor.fetchone()
            version = booking["version"]
            if result["status"] == "accepted":
                cursor = await conn.execute(
                    """
                    UPDATE bookings
                    SET status = 'confirmed', version = version + 1
                    WHERE id = %s
                      AND status = 'held'
                    RETURNING version
                    """,
                    (operation["booking_id"],),
                )
                confirmed = await cursor.fetchone()

                if confirmed is None:
                    status = "failed"
                    result = {
                        **result,
                        "review_required": True,
                        "reason": "booking_unavailable_after_charge",
                    }
                else:
                    version = confirmed["version"]

                    await conn.execute(
                        """
                        INSERT INTO tickets (id, booking_id, code)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (booking_id) DO NOTHING
                        """,
                        (
                            str(uuid4()),
                            operation["booking_id"],
                            str(uuid4()),
                        ),
                    )

                    status = "succeeded"
            else:
                status = "failed"

            event_type = (
                "payment.review_required"
                if result.get("review_required")
                else f"payment.{status}"
            )

            await conn.execute(
                """
                UPDATE operations
                SET status = %s, result = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, Jsonb(result), operation_id),
            )

            await conn.execute(
                """
                INSERT INTO outbox
                    (id, topic, event_type, aggregate_id,
                     aggregate_version, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid4()),
                    config.TOPIC_DOMAIN_EVENTS,
                    event_type,
                    operation["booking_id"],
                    version,
                    Jsonb({
                        "operation_id": operation_id,
                        "booking_id": operation["booking_id"],
                        "user_id": operation["user_id"],
                        "result": result,
                    }),
                ),
            )


            notification_id = str(uuid4())
            notification_type = event_type
            notification_payload = {
                "operation_id": operation_id,
                "booking_id": operation["booking_id"],
                "status": status,
                "result": result,
            }

            cursor = await conn.execute(
                """
                INSERT INTO notifications
                    (id, user_id, operation_id, type, payload)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING sequence_id
                """,
                (
                    notification_id,
                    operation["user_id"],
                    operation_id,
                    notification_type,
                    Jsonb(notification_payload),
                ),
            )

            sequence_id = (await cursor.fetchone())["sequence_id"]

            await conn.execute(
                """
                INSERT INTO outbox
                    (id, topic, event_type, aggregate_id,
                     aggregate_version, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    notification_id,
                    config.TOPIC_NOTIFICATIONS,
                    notification_type,
                    operation["user_id"],
                    sequence_id,
                    Jsonb({
                        "notification_id": notification_id,
                        "sequence_id": sequence_id,
                        **notification_payload,
                    }),
                ),
            )

            await conn.execute(
                """
                INSERT INTO processed_messages (handler, event_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (HANDLER, event_id),
            )

    log("payment.processed", operation_id=operation_id, status=status)


async def main(stop: asyncio.Event) -> None:
    await db.open_pool()

    task = asyncio.create_task(
        broker.consume(
            config.TOPIC_DOMAIN_EVENTS,
            config.GROUP_ID,
            handle,
        )
    )
    stopping = asyncio.create_task(stop.wait())

    log("worker.started")

    try:
        done, _ = await asyncio.wait(
            (task, stopping),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if task in done:
            await task
    finally:
        task.cancel()
        stopping.cancel()

        await asyncio.gather(
            task,
            stopping,
            return_exceptions=True,
        )

        await db.close_pool()
        log("worker.stopped")


if __name__ == "__main__":
    background.run(main)
