-- Number of receiver calls proves a Ray retry after effect commit without changing the effect twice.
ALTER TABLE scans ADD COLUMN receiver_calls integer NOT NULL DEFAULT 0 CHECK (receiver_calls >= 0);
