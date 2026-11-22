import asyncio

from . import background, broker, db
from .faults import fault
from .jsonlog import log


BATCH_SIZE = 10
POLL_INTERVAL = 1.0


async def publish_batch(producer) -> int:
    published = 0

    async with db.connection() as conn:
        async with conn.transaction():

            cursor = await conn.execute(
                """
                SELECT
                    id,
                    topic,
                    event_type,
                    aggregate_id,
                    aggregate_version,
                    payload,
                    occurred_at
                FROM outbox
                WHERE published_at IS NULL
                ORDER BY occurred_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (BATCH_SIZE,),
            )

            events = await cursor.fetchall()

            for row in events:
                event = {
                    "id": row["id"],
                    "type": row["event_type"],
                    "aggregate_id": row["aggregate_id"],
                    "aggregate_version": row["aggregate_version"],
                    "payload": row["payload"],
                    "occurred_at": row["occurred_at"].isoformat(),
                }

                fault("publisher_before_send")

                await broker.send(
                    producer,
                    topic=row["topic"],
                    key=row["aggregate_id"],
                    value=event,
                )

                await conn.execute(
                    """
                    UPDATE outbox
                    SET published_at = clock_timestamp()
                    WHERE id = %s
                      AND published_at IS NULL
                    """,
                    (row["id"],),
                )

                published += 1

    return published


async def wait_or_stop(
    stop: asyncio.Event, seconds: float
) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def main(stop: asyncio.Event) -> None:
    await db.open_pool()
    producer = None

    try:
        producer = await broker.start_producer()
        log("publisher.started")

        while not stop.is_set():
            try:
                count = await publish_batch(producer)

                if count:
                    log("publisher.batch", count=count)
                else:
                    await wait_or_stop(stop, POLL_INTERVAL)

            except Exception as exc:
                log("publisher.error", error=str(exc))
                await wait_or_stop(stop, 2.0)

    finally:
        if producer is not None:
            await producer.stop()

        await db.close_pool()
        log("publisher.stopped")


if __name__ == "__main__":
    background.run(main)
