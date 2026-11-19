-- C01 day-one contract. Apply via the shared migrate service, not by hand.
-- Web owns sales/bookings/tickets; DPC owns admission effects and sector occupancy.
-- Text IDs are supplied by applications. All times are instants, money is minor units.

CREATE TABLE users (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'staff')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE venues (
    id text PRIMARY KEY,
    name text NOT NULL,
    city text NOT NULL,
    time_zone text NOT NULL DEFAULT 'Europe/Kyiv'
);

-- events describe the programme; screenings are individual performances.
-- All integration performance_id values refer to screenings.id, not events.id.
CREATE TABLE events (
    id text PRIMARY KEY,
    title text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('cinema', 'concert')),
    description text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE screenings (
    id text PRIMARY KEY,
    event_id text NOT NULL REFERENCES events(id),
    venue_id text NOT NULL REFERENCES venues(id),
    starts_at timestamptz NOT NULL,
    duration_min integer NOT NULL CHECK (duration_min > 0),
    status text NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'cancelled', 'finished')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX screenings_programme ON screenings(event_id, starts_at, id);

-- Category inventory is the initial sales model. A category belongs to one performance.
CREATE TABLE seat_categories (
    id text PRIMARY KEY,
    screening_id text NOT NULL REFERENCES screenings(id),
    name text NOT NULL,
    capacity integer NOT NULL CHECK (capacity >= 0),
    available integer NOT NULL CHECK (available >= 0 AND available <= capacity),
    price_minor bigint NOT NULL CHECK (price_minor >= 0),
    currency text NOT NULL DEFAULT 'UAH' CHECK (currency ~ '^[A-Z]{3}$'),
    sales_open boolean NOT NULL DEFAULT true,
    UNIQUE (id, screening_id),
    UNIQUE (screening_id, name)
);

-- Empty until the explicit-seat extension (Web LR6). No allocation algorithm yet.
CREATE TABLE seats (
    id text PRIMARY KEY,
    screening_id text NOT NULL REFERENCES screenings(id),
    category_id text NOT NULL,
    row_label text NOT NULL,
    seat_number integer NOT NULL CHECK (seat_number > 0),
    FOREIGN KEY (category_id, screening_id) REFERENCES seat_categories(id, screening_id),
    UNIQUE (screening_id, row_label, seat_number)
);

-- bookings is the project's name for the course's hold entity.
CREATE TABLE bookings (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(id),
    screening_id text NOT NULL REFERENCES screenings(id),
    category_id text NOT NULL,
    seats integer NOT NULL CHECK (seats > 0),
    holder_name text NOT NULL,
    status text NOT NULL DEFAULT 'held'
        CHECK (status IN ('held', 'confirmed', 'expired', 'cancelled', 'refunded')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    hold_expires_at timestamptz NOT NULL,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    FOREIGN KEY (category_id, screening_id) REFERENCES seat_categories(id, screening_id),
    CHECK (hold_expires_at > created_at)
);
COMMENT ON COLUMN bookings.fencing_token IS
    'Reserved metadata, not a fencing implementation. DPC LR6 must register and check generations on its assignment resource.';
CREATE INDEX bookings_owner_recent ON bookings(user_id, created_at DESC, id DESC);
CREATE INDEX bookings_expiring ON bookings(hold_expires_at, id) WHERE status = 'held';

CREATE TABLE tickets (
    id text PRIMARY KEY,
    booking_id text NOT NULL UNIQUE REFERENCES bookings(id),
    code text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'valid' CHECK (status IN ('valid', 'refunded', 'cancelled')),
    issued_at timestamptz NOT NULL DEFAULT now()
);
-- Admission is an independent DPC effect: do not mark tickets consumed in Web.
CREATE TABLE sectors (
    id text PRIMARY KEY,
    screening_id text NOT NULL REFERENCES screenings(id),
    name text NOT NULL,
    capacity integer NOT NULL CHECK (capacity >= 0),
    inside integer NOT NULL DEFAULT 0 CHECK (inside >= 0),
    UNIQUE (screening_id, name)
);
COMMENT ON COLUMN sectors.inside IS
    'DPC must atomically enforce inside <= capacity; no upper CHECK so isolated unsafe experiments can demonstrate the race.';

CREATE TABLE outbox (
    id text PRIMARY KEY,
    topic text NOT NULL,
    event_type text NOT NULL,
    aggregate_id text NOT NULL,
    aggregate_version bigint NOT NULL CHECK (aggregate_version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    CHECK (published_at IS NULL OR published_at >= occurred_at)
);
CREATE INDEX outbox_pending ON outbox(occurred_at, id) WHERE published_at IS NULL;

CREATE TABLE processed_effects (
    handler text NOT NULL,
    effect_key text NOT NULL,
    event_id text NOT NULL,
    decision jsonb NOT NULL CHECK (jsonb_typeof(decision) = 'object'),
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (handler, effect_key)
);
COMMENT ON TABLE processed_effects IS
    'Dedupe + resource change + decision must share one transaction. Admission handler uses ticket_id as effect_key, not scan_id.';
