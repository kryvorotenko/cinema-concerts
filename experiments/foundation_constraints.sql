-- Integration smoke test. Always rolls back its fixtures, including on success.
BEGIN;
INSERT INTO users VALUES ('test-user','foundation@example.invalid','Test','not-a-real-hash','user',now());
INSERT INTO venues VALUES ('test-venue','Test venue','Kyiv','Europe/Kyiv');
INSERT INTO events(id,title,kind) VALUES ('test-event','Test','concert');
INSERT INTO screenings(id,event_id,venue_id,starts_at,duration_min)
VALUES ('test-screening','test-event','test-venue',now()+interval '1 day',120),
       ('other-screening','test-event','test-venue',now()+interval '2 days',120);
INSERT INTO seat_categories(id,screening_id,name,capacity,available,price_minor)
VALUES ('test-category','test-screening','General',50,50,10000);
INSERT INTO bookings(id,user_id,screening_id,category_id,seats,holder_name,hold_expires_at)
VALUES ('test-booking','test-user','test-screening','test-category',1,'Test',now()+interval '10 minutes');
INSERT INTO tickets(id,booking_id,code) VALUES ('test-ticket','test-booking','test-code');
INSERT INTO processed_effects VALUES ('admission','test-ticket','scan-1','{"accepted":true}',now());
DO $$
BEGIN
    BEGIN
        UPDATE seat_categories SET available = -1 WHERE id = 'test-category';
        RAISE EXCEPTION 'negative inventory accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO tickets(id,booking_id,code) VALUES ('duplicate-ticket','test-booking','other-code');
        RAISE EXCEPTION 'second ticket for booking accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO bookings(id,user_id,screening_id,category_id,seats,holder_name,hold_expires_at)
        VALUES ('wrong-screening','test-user','other-screening','test-category',1,'Test',now()+interval '10 minutes');
        RAISE EXCEPTION 'cross-performance category accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO processed_effects VALUES ('admission','test-ticket','scan-2','{"accepted":true}',now());
        RAISE EXCEPTION 'second admission effect for same ticket accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        UPDATE bookings SET hold_expires_at = created_at WHERE id='test-booking';
        RAISE EXCEPTION 'nonpositive hold duration accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;
ROLLBACK;
