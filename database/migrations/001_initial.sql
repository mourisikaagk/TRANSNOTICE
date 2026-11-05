CREATE TABLE agencies (
    id        INTEGER PRIMARY KEY,
    code      TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL,
    is_demo   INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1))
);

CREATE TABLE sources (
    id                INTEGER PRIMARY KEY,
    agency_id         INTEGER NOT NULL REFERENCES agencies (id),
    code              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    source_type       TEXT NOT NULL CHECK (source_type IN ('demo', 'html', 'rss')),
    url               TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    complete_listing  INTEGER NOT NULL DEFAULT 1 CHECK (complete_listing IN (0, 1)),
    timezone          TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    permission_status TEXT NOT NULL DEFAULT 'not_reviewed',
    refresh_minutes   INTEGER NOT NULL DEFAULT 15 CHECK (refresh_minutes > 0),
    last_attempt_at   TEXT,
    last_success_at   TEXT,
    last_status       TEXT CHECK (last_status IN ('success', 'failed')),
    last_error        TEXT
);

CREATE TABLE notices (
    id                INTEGER PRIMARY KEY,
    source_id         INTEGER NOT NULL REFERENCES sources (id),
    external_id       TEXT NOT NULL,
    title             TEXT NOT NULL,
    notice_type       TEXT NOT NULL,
    summary           TEXT,
    area              TEXT,
    source_url        TEXT,
    published_at      TEXT,
    valid_from        TEXT,
    valid_to          TEXT,
    withdrawn_at      TEXT,
    content_hash      TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL,
    last_changed_at   TEXT NOT NULL,
    UNIQUE (source_id, external_id),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX idx_notices_valid_to ON notices (valid_to);
CREATE INDEX idx_notices_last_changed ON notices (last_changed_at);
CREATE INDEX idx_notices_type ON notices (notice_type);

CREATE TABLE notice_routes (
    notice_id INTEGER NOT NULL REFERENCES notices (id) ON DELETE CASCADE,
    route_id  TEXT NOT NULL,
    PRIMARY KEY (notice_id, route_id)
) WITHOUT ROWID;
CREATE INDEX idx_notice_routes_route ON notice_routes (route_id);

CREATE TABLE notice_revisions (
    id              INTEGER PRIMARY KEY,
    notice_id       INTEGER NOT NULL REFERENCES notices (id) ON DELETE CASCADE,
    revision_no     INTEGER NOT NULL CHECK (revision_no >= 1),
    content_hash    TEXT NOT NULL,
    change_type     TEXT NOT NULL CHECK (change_type IN
                    ('new', 'revised', 'extended', 'shortened', 'routes_changed', 'withdrawn', 'reinstated')),
    change_summary  TEXT NOT NULL,
    changes_json    TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    observed_at     TEXT NOT NULL,
    UNIQUE (notice_id, revision_no)
);

CREATE TABLE audit_events (
    id         INTEGER PRIMARY KEY,
    notice_id  INTEGER REFERENCES notices (id) ON DELETE CASCADE,
    source_id  INTEGER REFERENCES sources (id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_audit_notice ON audit_events (notice_id, event_type);

CREATE TABLE subscriptions (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    route_filter TEXT,
    channel      TEXT NOT NULL DEFAULT 'demo' CHECK (channel IN ('demo', 'email')),
    email        TEXT,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at   TEXT NOT NULL,
    CHECK (channel <> 'email' OR email IS NOT NULL)
);

CREATE TABLE notifications (
    id              INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    notice_id       INTEGER NOT NULL REFERENCES notices (id) ON DELETE CASCADE,
    revision_id     INTEGER NOT NULL REFERENCES notice_revisions (id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'demo_logged', 'smtp_accepted', 'failed', 'skipped')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    alerted_at      TEXT,
    sent_at         TEXT,
    error           TEXT,
    UNIQUE (subscription_id, revision_id)
);
CREATE INDEX idx_notifications_status ON notifications (status);

CREATE TABLE scraper_runs (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources (id),
    trigger         TEXT NOT NULL CHECK (trigger IN ('scheduler', 'manual', 'cli')),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    http_status     INTEGER,
    attempts        INTEGER,
    items_found     INTEGER NOT NULL DEFAULT 0,
    new_count       INTEGER NOT NULL DEFAULT 0,
    revised_count   INTEGER NOT NULL DEFAULT 0,
    withdrawn_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    warning_count   INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT
);
CREATE INDEX idx_runs_source ON scraper_runs (source_id, started_at);
