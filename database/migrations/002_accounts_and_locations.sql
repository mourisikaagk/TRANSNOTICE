ALTER TABLE notices ADD COLUMN latitude REAL CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90);
ALTER TABLE notices ADD COLUMN longitude REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE user_routes (
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    route_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, route_id)
) WITHOUT ROWID;

ALTER TABLE subscriptions ADD COLUMN user_id INTEGER REFERENCES users (id) ON DELETE CASCADE;
CREATE INDEX idx_subscriptions_user ON subscriptions (user_id);
CREATE UNIQUE INDEX uq_subscription_user_route ON subscriptions (user_id, route_filter) WHERE user_id IS NOT NULL;
