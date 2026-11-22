
from uuid import uuid4

from psycopg.types.json import Jsonb

from . import config, db


async def create_payment(
    booking_id: str,
    user_id: str,
    idempotency_key: str,
) -> str:
    if not idempotency_key:
        raise ValueError("Idempotency-Key is required")

    async with db.connection() as conn:
        async with conn.transaction():
            cursor = await conn.execute(
                """
                SELECT id, booking_id
                FROM operations
                WHERE user_id = %s AND idempotency_key = %s
                """,
                (user_id, idempotency_key),
            )
            existing = await cursor.fetchone()

            if existing:
                if existing["booking_id"] != booking_id:
                    raise ValueError("Idempotency-Key already used")
                return existing["id"]

            cursor = await conn.execute(
                """
                SELECT b.id, b.user_id, b.status,
                       b.hold_expires_at, b.version, b.seats,
                       c.price_minor, c.currency
                FROM bookings b
                JOIN seat_categories c
                    ON c.id = b.category_id
                   AND c.screening_id = b.screening_id
                WHERE b.id = %s
                FOR UPDATE OF b
                """,
                (booking_id,),
            )
            booking = await cursor.fetchone()

            if booking is None or booking["user_id"] != user_id:
                raise LookupError("Booking not found")

            cursor = await conn.execute(
                """
                SELECT id, booking_id
                FROM operations
                WHERE user_id = %s AND idempotency_key = %s
                """,
                (user_id, idempotency_key),
            )
            existing = await cursor.fetchone()

            if existing:
                if existing["booking_id"] != booking_id:
                    raise ValueError("Idempotency-Key already used")
                return existing["id"]

            cursor = await conn.execute(
                """
                SELECT id
                FROM operations
                WHERE booking_id = %s
                  AND status IN ('pending', 'running', 'succeeded')
                LIMIT 1
                """,
                (booking_id,),
            )

            if await cursor.fetchone():
                raise ValueError("Payment already exists for this booking")

            cursor = await conn.execute(
                "SELECT now() AS current_time"
            )
            current_time = (await cursor.fetchone())["current_time"]

            if (
                booking["status"] != "held"
                or booking["hold_expires_at"] <= current_time
            ):
                raise ValueError("Booking is not available for payment")

            amount = booking["seats"] * booking["price_minor"]

            if amount <= 0:
                raise ValueError("Payment amount must be positive")

            operation_id = str(uuid4())

            cursor = await conn.execute(
                """
                INSERT INTO operations
                    (id, booking_id, user_id, idempotency_key,
                     amount_cents, currency)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING id
                """,
                (
                    operation_id,
                    booking_id,
                    user_id,
                    idempotency_key,
                    amount,
                    booking["currency"],
                ),
            )

            inserted = await cursor.fetchone()

            if inserted is None:
                cursor = await conn.execute(
                    """
                    SELECT id, booking_id
                    FROM operations
                    WHERE user_id = %s AND idempotency_key = %s
                    """,
                    (user_id, idempotency_key),
                )
                existing = await cursor.fetchone()

                if existing["booking_id"] != booking_id:
                    raise ValueError("Idempotency-Key already used")
                return existing["id"]

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
                    "payment.requested",
                    booking_id,
                    booking["version"],
                    Jsonb({
                        "operation_id": operation_id,
                        "booking_id": booking_id,
                    }),
                ),
            )

            return operation_id
