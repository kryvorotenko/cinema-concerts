CREATE TABLE sessions (
    token_hash text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX sessions_user_idx ON sessions (user_id);
CREATE INDEX sessions_expires_idx ON sessions (expires_at);

UPDATE users SET password_hash = 'scrypt$16384$8$1$oaGhoaGhoaGhoaGhoaGhoQ==$blxU5QK4yh3jn0z8V6tZ2ukcdVZkjpAdiNJGU0Omc5s='
WHERE id = 'usr-alice' AND password_hash = '!set-in-lab3';

UPDATE users SET password_hash = 'scrypt$16384$8$1$srKysrKysrKysrKysrKysg==$rv+NL2M+kMUmPtBUhQ0gttnd1JE0n6yn4y0wP8uFkkw='
WHERE id = 'usr-bob' AND password_hash = '!set-in-lab3';

UPDATE users SET password_hash = 'scrypt$16384$8$1$w8PDw8PDw8PDw8PDw8PDww==$W3/HGEp9tMxbijBwBe4WJLPFxSO+rE7WCtDpt6q6uB8='
WHERE id = 'usr-staff' AND password_hash = '!set-in-lab3';
