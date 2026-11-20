-- Isolated LR1 fixtures; never use these IDs for shared Web data.
INSERT INTO users(id,email,display_name,password_hash) VALUES
('dpc-test-user','dpc-test@example.invalid','DPC fixture','unused') ON CONFLICT DO NOTHING;
INSERT INTO venues(id,name,city) VALUES ('dpc-test-venue','Test venue','Test') ON CONFLICT DO NOTHING;
INSERT INTO events(id,title,kind) VALUES ('dpc-test-event','Test concert','concert') ON CONFLICT DO NOTHING;
INSERT INTO screenings(id,event_id,venue_id,starts_at,duration_min) VALUES
('dpc-test-performance','dpc-test-event','dpc-test-venue',now()+interval '1 day',120) ON CONFLICT DO NOTHING;
INSERT INTO seat_categories(id,screening_id,name,capacity,available,price_minor) VALUES
('dpc-test-category','dpc-test-performance','Fixture',1000,1000,100) ON CONFLICT DO NOTHING;
INSERT INTO sectors(id,screening_id,name,capacity) VALUES
('dpc-test-sector','dpc-test-performance','Fixture sector',2) ON CONFLICT DO NOTHING;
INSERT INTO bookings(id,user_id,screening_id,category_id,seats,holder_name,status,hold_expires_at)
SELECT 'dpc-test-booking-'||n,'dpc-test-user','dpc-test-performance','dpc-test-category',1,'Fixture','confirmed',now()+interval '1 day'
FROM generate_series(1,30) AS n ON CONFLICT DO NOTHING;
INSERT INTO tickets(id,booking_id,code)
SELECT 'dpc-test-ticket-'||n,'dpc-test-booking-'||n,'dpc-test-code-'||n
FROM generate_series(1,30) AS n ON CONFLICT DO NOTHING;
