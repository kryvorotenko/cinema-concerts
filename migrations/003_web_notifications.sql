-- Stored user notifications.

CREATE TABLE notifications (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(id),
    operation_id text REFERENCES operations(id),
    type text NOT NULL,
    payload jsonb NOT NULL,
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT notifications_payload_check
        CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT notifications_operation_type_unique
        UNIQUE (operation_id, type)
);

CREATE INDEX notifications_user_sequence_idx
    ON notifications (user_id, sequence_id);
