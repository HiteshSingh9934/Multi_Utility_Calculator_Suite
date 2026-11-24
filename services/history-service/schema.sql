-- history-service owns this table; no other service talks to PostgreSQL.
-- Applied automatically every time history-service starts (it is safe to run repeatedly).

CREATE TABLE IF NOT EXISTS history (
    id          BIGSERIAL    PRIMARY KEY,
    tool        VARCHAR(40)  NOT NULL,   -- calculator, unit-converter, gst, emi, cgpa, grades, attendance
    service     VARCHAR(40)  NOT NULL,   -- which microservice produced the result
    summary     TEXT         NOT NULL,   -- one readable line, e.g. "10 km = 6.213712 mi"
    input       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    result      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    served_by   VARCHAR(100),            -- container ID (Docker) or pod name (Kubernetes)
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS history_created_at_idx ON history (created_at DESC);
CREATE INDEX IF NOT EXISTS history_tool_idx ON history (tool);

-- One-time data migrations that have already run (so they never run twice)
CREATE TABLE IF NOT EXISTS migrations (
    name        TEXT         PRIMARY KEY,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
