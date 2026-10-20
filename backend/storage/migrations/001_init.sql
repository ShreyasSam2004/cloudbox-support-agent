-- Core application tables. Knowledge-base tables (kb_*) are created by PgVectorStore.ensure_index
-- because their vector dimension depends on the configured embedding model.

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    data        JSONB       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    owner             TEXT        NOT NULL,
    bound_customer_id TEXT,
    data              JSONB       NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_updated_at_idx ON sessions (updated_at);

CREATE TABLE IF NOT EXISTS agent_traces (
    execution_id TEXT PRIMARY KEY,
    session_id   TEXT        NOT NULL,
    request_id   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    data         JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_traces_session_idx ON agent_traces (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_traces_created_at_idx ON agent_traces (created_at);
