-- DPC LR1: request lifecycle. The in-memory queue is intentionally not crash durable.
CREATE TABLE scans (
    id text PRIMARY KEY,
    ticket_id text NOT NULL,
    ticket_code text NOT NULL,
    gate text NOT NULL,
    sector_id text NOT NULL REFERENCES sectors(id),
    event_time timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('queued','processing','done','rejected','failed')),
    decision jsonb,
    error_code text,
    arrived_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CHECK ((state IN ('queued','processing') AND finished_at IS NULL) OR
           (state IN ('done','rejected','failed') AND finished_at IS NOT NULL))
);
CREATE INDEX scans_state_arrival ON scans(state, arrived_at);
