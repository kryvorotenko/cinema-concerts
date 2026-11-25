INSERT INTO sectors (id, screening_id, name, capacity) VALUES
    ('e2e-sector-jazz', 'scr-jazz-1', 'E2E партер',  2),
    ('e2e-sector-film', 'scr-film-1', 'E2E зал',     5)
ON CONFLICT (id) DO NOTHING;

DELETE FROM scans WHERE id LIKE 'e2e-%';
DELETE FROM processed_effects
WHERE handler = 'admission' AND effect_key IN ('tkt-demo-1', 'tkt-demo-2', 'tkt-demo-3');
UPDATE sectors SET inside = 0 WHERE id IN ('e2e-sector-jazz', 'e2e-sector-film');
