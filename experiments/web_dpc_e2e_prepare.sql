-- Web <-> DPC end-to-end: sectors for the Web demo performances and a clean slate for the DPC side.
-- DPC owns `sectors`, `scans` and admission effects; these rows exist only for experiments/test_web_dpc_e2e.py.
-- Safe to repeat. Only e2e-* rows and the effects of the three demo tickets are touched.
INSERT INTO sectors (id, screening_id, name, capacity) VALUES
    ('e2e-sector-jazz', 'scr-jazz-1', 'E2E партер',  2),
    ('e2e-sector-film', 'scr-film-1', 'E2E зал',     5)
ON CONFLICT (id) DO NOTHING;

DELETE FROM scans WHERE id LIKE 'e2e-%';
DELETE FROM processed_effects
WHERE handler = 'admission' AND effect_key IN ('tkt-demo-1', 'tkt-demo-2', 'tkt-demo-3');
UPDATE sectors SET inside = 0 WHERE id IN ('e2e-sector-jazz', 'e2e-sector-film');
