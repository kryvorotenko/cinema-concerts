CREATE TABLE idempotency_keys (
    user_id text NOT NULL REFERENCES users(id),
    key text NOT NULL,
    operation text NOT NULL,
    fingerprint text NOT NULL,
    state text NOT NULL DEFAULT 'completed',
    status_code integer NOT NULL,
    response_body jsonb NOT NULL,
    location text,
    etag text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (user_id, key),
    CONSTRAINT idempotency_keys_state_check CHECK (state IN ('completed')),
    CONSTRAINT idempotency_keys_key_check CHECK (length(key) BETWEEN 1 AND 255)
);

CREATE INDEX idempotency_keys_expires_idx ON idempotency_keys (expires_at);
