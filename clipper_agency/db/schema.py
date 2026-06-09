"""Database schema definition and initialization."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    config TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'tiktok',
    platform_username TEXT,
    is_active INTEGER DEFAULT 1,
    config_overrides TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    niche TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    template TEXT,
    account_id INTEGER REFERENCES accounts(id),
    config_snapshot TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    agent_name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    input_data TEXT,
    output_data TEXT,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    UNIQUE(job_id, agent_name)
);

CREATE TABLE IF NOT EXISTS agent_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    model TEXT,
    temperature REAL,
    max_tokens INTEGER,
    prompt_version TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(agent_name, prompt_version)
);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    style TEXT NOT NULL,
    config TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    source_url TEXT,
    local_path TEXT,
    provider TEXT,
    license_info TEXT,
    content_hash TEXT,
    duration_seconds REAL,
    file_size_bytes INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,
    topic TEXT NOT NULL,
    data TEXT NOT NULL,
    freshness TEXT DEFAULT 'fresh',
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    video_path TEXT,
    caption_path TEXT,
    thumbnail_path TEXT,
    metadata_path TEXT,
    video_duration_seconds REAL,
    file_size_bytes INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT,
    resource_type TEXT,
    resource_id INTEGER,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_type TEXT NOT NULL,
    config_data TEXT NOT NULL,
    version INTEGER NOT NULL,
    diff_from_previous TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    diff_from_previous TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(agent_name, version)
);

CREATE TABLE IF NOT EXISTS creative_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    topic_cluster TEXT NOT NULL,
    angle TEXT,
    template_used TEXT,
    assets_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    snapshot_data TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS preflight_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    estimated_cost REAL,
    estimated_credits_used INTEGER,
    provider_breakdown TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_agent_states_job ON agent_states(job_id);
CREATE INDEX IF NOT EXISTS idx_research_cache_key ON research_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
"""


def initialize_schema(conn) -> None:
    """Create all database tables if they don't exist."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    ensure_status_columns(conn)


def ensure_status_columns(conn) -> None:
    """Add lifecycle status columns to jobs table if missing.

    Idempotent — safe to call multiple times.
    """
    _STATUS_COLUMNS = [
        ("quality_status", "TEXT NOT NULL DEFAULT 'not_reviewed'"),
        ("publication_status", "TEXT NOT NULL DEFAULT 'blocked'"),
        ("repair_status", "TEXT NOT NULL DEFAULT 'none'"),
        ("artifact_status", "TEXT NOT NULL DEFAULT 'candidate'"),
    ]
    for col_name, col_def in _STATUS_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # Column already exists — safe to ignore
    conn.commit()


def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cursor.fetchone() is not None
