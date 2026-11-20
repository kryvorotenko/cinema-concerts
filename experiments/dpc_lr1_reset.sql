-- Reset only DPC LR1 isolated effects; preserve shared/Web records.
DELETE FROM processed_effects WHERE handler='admission' AND effect_key LIKE 'dpc-test-%';
UPDATE sectors SET inside=0 WHERE id='dpc-test-sector';
