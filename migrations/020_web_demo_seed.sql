INSERT INTO users (id, email, display_name, password_hash, role) VALUES
    ('usr-alice', 'alice@example.invalid', 'Аліса Коваль', '!set-in-lab3', 'user'),
    ('usr-bob',   'bob@example.invalid',   'Богдан Мельник', '!set-in-lab3', 'user'),
    ('usr-staff', 'staff@example.invalid', 'Олена Адмін', '!set-in-lab3', 'staff');

INSERT INTO venues (id, name, city, time_zone) VALUES
    ('venue-central', 'Центральна концертна зала', 'Харків', 'Europe/Kyiv');

INSERT INTO events (id, title, kind, description) VALUES
    ('event-jazz',  'Нічний джаз',      'concert', 'Вечір живого джазу'),
    ('event-film',  'Вечірній сеанс',   'cinema',  'Показ у великому залі');

INSERT INTO screenings (id, event_id, venue_id, starts_at, duration_min) VALUES
    ('scr-jazz-1', 'event-jazz', 'venue-central', '2035-06-01 19:00:00+03', 150),
    ('scr-film-1', 'event-film', 'venue-central', '2035-06-02 20:30:00+03', 120);

INSERT INTO seat_categories (id, screening_id, name, capacity, available, price_minor, currency, sales_open) VALUES
    ('cat-jazz-vip',  'scr-jazz-1', 'VIP',            20,  19, 150000, 'UAH', true),
    ('cat-jazz-std',  'scr-jazz-1', 'Стандарт',       200, 200, 60000, 'UAH', true),
    ('cat-scarce',    'scr-jazz-1', 'Останні місця',  5,   5,   40000, 'UAH', true),
    ('cat-race-50',   'scr-jazz-1', 'Гонка 50',       50,  50,  30000, 'UAH', true),
    ('cat-closed',    'scr-jazz-1', 'Закрита',        10,  10,  20000, 'UAH', false),
    ('cat-film-std',  'scr-film-1', 'Партер',         100, 99,  25000, 'UAH', true);

INSERT INTO bookings (id, user_id, screening_id, category_id, seats, holder_name, status, hold_expires_at) VALUES
    ('bk-demo-1', 'usr-alice', 'scr-jazz-1', 'cat-jazz-vip', 1, 'Аліса Коваль', 'confirmed', now() + interval '10 minutes'),
    ('bk-demo-2', 'usr-bob',   'scr-jazz-1', 'cat-jazz-vip', 1, 'Богдан Мельник', 'refunded', now() + interval '10 minutes'),
    ('bk-demo-3', 'usr-alice', 'scr-film-1', 'cat-film-std', 1, 'Аліса Коваль', 'confirmed', now() + interval '10 minutes');

INSERT INTO tickets (id, booking_id, code, status) VALUES
    ('tkt-demo-1', 'bk-demo-1', 'TKT-DEMO-0001', 'valid'),
    ('tkt-demo-2', 'bk-demo-2', 'TKT-DEMO-0002', 'refunded'),
    ('tkt-demo-3', 'bk-demo-3', 'TKT-DEMO-0003', 'valid');
