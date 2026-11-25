DELETE FROM idempotency_keys;

DELETE FROM bookings
WHERE id NOT LIKE 'bk-demo-%' AND id NOT LIKE 'dpc-test-%' AND status IN ('held', 'expired', 'cancelled')
  AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.booking_id = bookings.id);

UPDATE seat_categories c
SET available = c.capacity - COALESCE((
    SELECT sum(b.seats) FROM bookings b WHERE b.category_id = c.id AND b.status IN ('held', 'confirmed')), 0)
WHERE c.id IN ('cat-jazz-vip', 'cat-jazz-std', 'cat-scarce', 'cat-race-50', 'cat-closed', 'cat-film-std');

UPDATE seat_categories SET sales_open = (id <> 'cat-closed') WHERE id LIKE 'cat-%';
