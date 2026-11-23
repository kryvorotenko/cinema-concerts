-- DPC LR6 projection of Web-pre-reserved returned seats and fenced assignments.
CREATE TABLE coordination_state (
    id text PRIMARY KEY CHECK (id = 'waitlist'),
    generation bigint NOT NULL CHECK (generation >= 0),
    owner text NOT NULL,
    registered_at timestamptz
);
INSERT INTO coordination_state(id,generation,owner) VALUES ('waitlist',0,'');

CREATE TABLE waitlist_entries (
    id text PRIMARY KEY,
    performance_id text NOT NULL REFERENCES screenings(id),
    buyer_id text NOT NULL REFERENCES users(id),
    status text NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting','assigned')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (performance_id,buyer_id)
);
CREATE INDEX waitlist_pending ON waitlist_entries(performance_id,created_at,id) WHERE status='waiting';

CREATE TABLE returned_reserves (
    web_reserve_id text PRIMARY KEY,
    performance_id text NOT NULL REFERENCES screenings(id),
    seat_id text NOT NULL,
    status text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','assigned')),
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (performance_id,seat_id)
);
CREATE INDEX returned_reserves_ready ON returned_reserves(received_at,web_reserve_id) WHERE status='ready';

CREATE TABLE waitlist_assignments (
    assignment_id text PRIMARY KEY,
    web_reserve_id text NOT NULL UNIQUE REFERENCES returned_reserves(web_reserve_id),
    waitlist_id text NOT NULL UNIQUE REFERENCES waitlist_entries(id),
    generation bigint NOT NULL CHECK (generation > 0),
    owner text NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE coordination_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('register','assigned','rejected')),
    generation bigint NOT NULL,
    owner text NOT NULL,
    web_reserve_id text,
    waitlist_id text,
    reason text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX coordination_history_order ON coordination_history(id);
