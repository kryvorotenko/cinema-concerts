-- Payment operations and processed Kafka messages.

CREATE TABLE operations (
    id text PRIMARY KEY,
    booking_id text NOT NULL REFERENCES bookings(id),
    user_id text NOT NULL REFERENCES users(id),
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    amount_cents bigint NOT NULL,
    currency text NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT operations_status_check
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    CONSTRAINT operations_amount_check
        CHECK (amount_cents > 0),
    CONSTRAINT operations_idempotency_unique
        UNIQUE (user_id, idempotency_key)
);

CREATE INDEX operations_booking_idx
    ON operations (booking_id);

CREATE TABLE processed_messages (
    handler text NOT NULL,
    event_id text NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (handler, event_id)
);
