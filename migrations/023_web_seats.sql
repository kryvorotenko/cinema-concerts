CREATE TABLE booking_seats (
    seat_id text PRIMARY KEY REFERENCES seats(id),
    booking_id text NOT NULL REFERENCES bookings(id) ON DELETE CASCADE
);
CREATE INDEX booking_seats_booking ON booking_seats(booking_id);

CREATE FUNCTION release_booking_seats() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM booking_seats WHERE booking_id = NEW.id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER bookings_release_seats
AFTER UPDATE OF status ON bookings
FOR EACH ROW
WHEN (NEW.status IN ('expired', 'cancelled', 'refunded') AND OLD.status IN ('held', 'confirmed'))
EXECUTE FUNCTION release_booking_seats();

CREATE TABLE feature_flags (
    name text PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO feature_flags (name, enabled) VALUES ('explicit-seats', false);
