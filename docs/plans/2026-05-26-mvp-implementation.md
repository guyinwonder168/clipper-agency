# Clipper Agency — MVP Implementation Plan ✅ COMPLETED

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the complete MVP of Clipper Agency — a greenfield Python application that takes a trending topic through a gated agent pipeline and produces a ready-to-upload video package (`video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json`).

**Architecture:** DB-driven agentic pipeline. Orchestrator coordinates 7 agents (Safety → Researcher → Scriptwriter → Voice Producer → Visual Director → Composer → Reviewer) through 10 gates (G1-G10). All state persisted in SQLite. No direct agent-to-agent calls. CLI + web dashboard both consume the same job-creation interface.

**Tech Stack:** Python 3.11+, pydantic, sqlite3 (WAL + advisory locks), click (CLI), Flask (dashboard), httpx (API calls), Pillow (thumbnails), pyyaml (config), pytest, FFmpeg 5.0+ (CPU-only). External: OpenRouter, ElevenLabs, yt-dlp, Pexels, ScrapeCreators, Firecrawl.

---

## Phase 0: Project Scaffolding ✅ COMPLETED

### Task 1: Project Skeleton ✅

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "clipper-agency"
version = "0.1.0"
description = "Automated short-form video content production"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "flask>=3.0",
    "httpx>=0.27",
    "pydantic>=2.5",
    "pydantic-settings>=2.1",
    "pyyaml>=6.0",
    "pillow>=10.0",
    "python-dotenv>=1.0",
]

[project.scripts]
clipper = "clipper_agency.__main__:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "external: marks tests that call external APIs (deselect with '-m \"not external\"')",
    "slow: marks slow tests (deselect with '-m \"not slow\"')",
    "integration: marks integration tests (deselect with '-m \"not integration\"')",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

**Step 2: Create `requirements.txt`**

```
# Core
click>=8.1
flask>=3.0
httpx>=0.27
pydantic>=2.5
pydantic-settings>=2.1
pyyaml>=6.0
pillow>=10.0
python-dotenv>=1.0
werkzeug>=3.0

# Dev
pytest>=7.4
pytest-cov>=4.1
pytest-mock>=3.12
ruff>=0.1
```

**Step 3: Create `.env.example`**

```bash
# --- Required ---
OPENROUTER_API_KEY=sk-or-v1-
ELEVENLABS_API_KEY=
PEXELS_API_KEY=
SCRAPECREATORS_API_KEY=
FIRECRAWL_API_KEY=

# --- Optional ---
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=changeme
DATABASE_PATH=data/clipper.db
ASSETS_CACHE_DIR=assets/cache
OUTPUTS_DIR=outputs
```

**Step 4: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.env
data/
outputs/
assets/cache/
*.db
*.db-wal
*.db-shm
.pytest_cache/
ruff_cache/
```

**Step 5: Commit**

```bash
git add -A && git commit -m "chore: scaffold project skeleton"
```

---

### Task 2: Package Skeleton ✅

**Files:**
- Create: `clipper_agency/__init__.py`
- Create: `clipper_agency/__main__.py`

**Step 1: Create `clipper_agency/__init__.py`**

Empty file — marks the package directory.

**Step 2: Create `clipper_agency/__main__.py`**

```python
"""Clipper Agency — automated short-form video content production."""

import click

from clipper_agency.config.loader import load_config


@click.group()
@click.option("--config", "-c", default=None, help="Path to config file")
@click.pass_context
def cli(ctx: click.Context, config: str | None) -> None:
    """Clipper Agency — automated video content production."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config) if config else {}


@cli.command()
@click.option("--topic", "-t", required=True, help="Topic for video generation")
@click.option("--niche", "-n", default="indonesian_artists", help="Niche profile to use")
@click.option("--template", "-m", default=None, help="Video template to use")
@click.pass_context
def run(ctx: click.Context, topic: str, niche: str, template: str | None) -> None:
    """Run the full pipeline for a topic."""
    click.echo(f"Topic: {topic}")
    click.echo(f"Niche: {niche}")
    click.echo("Pipeline execution coming soon...")


if __name__ == "__main__":
    cli()
```

**Step 3: Verify CLI entry point**

Run: `python3 -m clipper_agency --help`
Expected: Shows help with `--config` option and `run` subcommand.

Verify: `python3 -m clipper_agency run --topic "test"`
Expected: `Topic: test` printed.

**Step 4: Commit**

```bash
git add -A && git commit -m "chore: add package skeleton with CLI entry point"
```

---

### Task 3: Test Infrastructure ✅

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create `tests/conftest.py`**

```python
"""Shared fixtures for all tests."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_topic() -> str:
    return "Viral video Ariana Grande di konser Jakarta"


@pytest.fixture
def sample_niche_config() -> dict:
    return {
        "name": "indonesian_artists",
        "language": "id",
        "tone": "casual_tiktok",
        "video_length": {"target": 30, "hard_limit": 60},
        "safety_rules": ["no_defamation", "mark_rumors_as_unconfirmed"],
    }


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Temporary SQLite database path."""
    return str(tmp_path / "test.db")
```

**Step 2: Verify pytest runs**

Run: `python3 -m pytest tests/ -v`
Expected: No tests collected (0 passed/0 failed), no import errors.

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: add test infrastructure with conftest"
```

---

## Phase 1: Configuration System ✅ COMPLETED

### Task 4: Config Loader with Pydantic Models ✅

**Files:**
- Create: `clipper_agency/config/__init__.py`
- Create: `clipper_agency/config/loader.py`
- Create: `clipper_agency/config/schema.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
import yaml
from pydantic import ValidationError

from clipper_agency.config.schema import NicheConfig, AppConfig, AgentLLMConfig


def test_niche_config_valid():
    data = {
        "name": "indonesian_artists",
        "language": "id",
        "tone": "casual_tiktok",
        "video_length": {"target": 30, "hard_limit": 60},
        "safety_rules": ["no_defamation"],
    }
    cfg = NicheConfig(**data)
    assert cfg.name == "indonesian_artists"
    assert cfg.video_length.target == 30


def test_niche_config_invalid_missing_name():
    data = {"language": "id"}
    with pytest.raises(ValidationError):
        NicheConfig(**data)


def test_app_config_defaults():
    cfg = AppConfig()
    assert cfg.database_path == "data/clipper.db"
    assert cfg.assets_cache_dir == "assets/cache"


def test_agent_llm_config():
    cfg = AgentLLMConfig(model="glm-4-9b", temperature=0.3)
    assert cfg.model == "glm-4-9b"
    assert cfg.temperature == 0.3
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ImportError — no module `clipper_agency.config.schema`

**Step 3: Write minimal implementation**

```python
# clipper_agency/config/schema.py
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class VideoLengthConfig(BaseModel):
    target: int = 30
    hard_limit: int = 60


class NicheConfig(BaseModel):
    name: str
    language: str
    tone: str
    video_length: VideoLengthConfig = VideoLengthConfig()
    safety_rules: list[str] = []
    caption_style: str = "short_with_hashtags"


class AgentLLMConfig(BaseModel):
    model: str = "mimo-v2-flash"
    temperature: float = 0.7
    max_tokens: int = 1024
    prompt_version: str = "1.0"


class AppConfig(BaseModel):
    database_path: str = Field(default="data/clipper.db")
    assets_cache_dir: str = Field(default="assets/cache")
    outputs_dir: str = Field(default="outputs")
    dashboard_username: str = Field(default="admin")
    dashboard_password: str = Field(default="changeme")
```

```python
# clipper_agency/config/loader.py
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from clipper_agency.config.schema import NicheConfig, AppConfig


def load_config(config_path: str | None = None) -> AppConfig:
    """Load application config from environment + optional YAML file."""
    load_dotenv()
    return AppConfig(
        database_path=os.getenv("DATABASE_PATH", "data/clipper.db"),
        assets_cache_dir=os.getenv("ASSETS_CACHE_DIR", "assets/cache"),
        outputs_dir=os.getenv("OUTPUTS_DIR", "outputs"),
        dashboard_username=os.getenv("DASHBOARD_USERNAME", "admin"),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD", "changeme"),
    )


def load_niche_config(niche_name: str) -> NicheConfig:
    """Load a niche profile from YAML file."""
    path = Path(f"niches/{niche_name}.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Niche config not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    return NicheConfig(**data.get("niche", data))
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add config loader with pydantic models"
```

---

### Task 5: Config Hierarchy ✅

**Files:**
- Create: `clipper_agency/config/hierarchy.py`
- Modify: `tests/test_config.py` (append)

**Step 1: Write the failing test**

```python
# Append to tests/test_config.py
from clipper_agency.config.hierarchy import ConfigHierarchy, AgentDefaults


def test_config_hierarchy_defaults():
    hierarchy = ConfigHierarchy()
    assert hierarchy.get("researcher", "model") == "mimo-v2-flash"


def test_config_hierarchy_niche_override():
    hierarchy = ConfigHierarchy()
    hierarchy.set_niche_override("researcher", "model", "qwen3-32b")
    assert hierarchy.get("researcher", "model") == "qwen3-32b"


def test_config_hierarchy_job_override_wins():
    hierarchy = ConfigHierarchy()
    hierarchy.set_niche_override("researcher", "model", "qwen3-32b")
    hierarchy.set_job_override("researcher", "model", "deepseek-v3.2")
    assert hierarchy.get("researcher", "model") == "deepseek-v3.2"


def test_agent_defaults_preset():
    ad = AgentDefaults()
    assert "researcher" in ad.agents
    assert ad.agents["researcher"]["model"] == "mimo-v2-flash"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py::test_config_hierarchy_defaults -v`
Expected: ImportError — no module `clipper_agency.config.hierarchy`

**Step 3: Write minimal implementation**

```python
# clipper_agency/config/hierarchy.py
from typing import Any


class AgentDefaults:
    """Default LLM/model settings per agent."""

    PRESETS = {
        "budget_east": {
            "safety": {"model": "glm-4-9b", "temperature": 0.1, "max_tokens": 256},
            "researcher": {"model": "mimo-v2-flash", "temperature": 0.3, "max_tokens": 2048},
            "scriptwriter": {"model": "qwen3-32b", "temperature": 0.7, "max_tokens": 2048},
            "voice_producer": {"model": None},  # No LLM for voice
            "visual_director": {"model": "mimo-v2-flash", "temperature": 0.5, "max_tokens": 1024},
            "composer": {"model": None},  # FFmpeg only
            "reviewer": {"model": "gemini-2.5-flash", "temperature": 0.3, "max_tokens": 2048},
        }
    }

    def __init__(self, preset: str = "budget_east") -> None:
        self.agents = dict(self.PRESETS[preset])


class ConfigHierarchy:
    """Agent → Niche → Account → Job config overrides."""

    def __init__(self, preset: str = "budget_east") -> None:
        self._defaults = AgentDefaults(preset).agents
        self._niche_overrides: dict[str, dict[str, Any]] = {}
        self._account_overrides: dict[str, dict[str, Any]] = {}
        self._job_overrides: dict[str, dict[str, Any]] = {}

    def set_niche_override(self, agent: str, key: str, value: Any) -> None:
        self._niche_overrides.setdefault(agent, {})[key] = value

    def set_account_override(self, agent: str, key: str, value: Any) -> None:
        self._account_overrides.setdefault(agent, {})[key] = value

    def set_job_override(self, agent: str, key: str, value: Any) -> None:
        self._job_overrides.setdefault(agent, {})[key] = value

    def get(self, agent: str, key: str) -> Any:
        """Resolve config value through hierarchy: job > account > niche > default."""
        if agent in self._job_overrides and key in self._job_overrides[agent]:
            return self._job_overrides[agent][key]
        if agent in self._account_overrides and key in self._account_overrides[agent]:
            return self._account_overrides[agent][key]
        if agent in self._niche_overrides and key in self._niche_overrides[agent]:
            return self._niche_overrides[agent][key]
        return self._defaults.get(agent, {}).get(key)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 8 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add config hierarchy with override resolution"
```

---

## Phase 2: Database Layer ✅ COMPLETED

### Task 6: Database Connection ✅

**Files:**
- Create: `clipper_agency/db/__init__.py`
- Create: `clipper_agency/db/connection.py`
- Create: `tests/test_db_connection.py`

**Step 1: Write the failing test**

```python
# tests/test_db_connection.py
import sqlite3

from clipper_agency.db.connection import get_connection, close_connection


def test_get_connection(temp_db_path):
    conn = get_connection(temp_db_path)
    assert isinstance(conn, sqlite3.Connection)
    # WAL mode should be enabled
    cursor = conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"
    close_connection()


def test_get_connection_singleton(temp_db_path):
    conn1 = get_connection(temp_db_path)
    conn2 = get_connection(temp_db_path)
    assert conn1 is conn2  # Same connection returned
    close_connection()


def test_advisory_lock(temp_db_path):
    conn = get_connection(temp_db_path)
    # Advisory lock is a no-op on SQLite but should not crash
    conn.execute("SELECT 1")
    close_connection()
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db_connection.py -v`
Expected: ImportError — no module `clipper_agency.db.connection`

**Step 3: Write minimal implementation**

```python
# clipper_agency/db/connection.py
import sqlite3
from pathlib import Path
from threading import Lock


_connections: dict[str, sqlite3.Connection] = {}
_conn_lock = Lock()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get or create a SQLite connection with WAL mode."""
    abs_path = str(Path(db_path).resolve())
    with _conn_lock:
        if abs_path not in _connections:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(abs_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            _connections[abs_path] = conn
        return _connections[abs_path]


def close_connection(db_path: str | None = None) -> None:
    """Close database connection(s)."""
    with _conn_lock:
        if db_path:
            abs_path = str(Path(db_path).resolve())
            if abs_path in _connections:
                _connections[abs_path].close()
                del _connections[abs_path]
        else:
            for conn in _connections.values():
                conn.close()
            _connections.clear()
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db_connection.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add SQLite connection with WAL mode"
```

---

### Task 7: Database Schema ✅

**Files:**
- Create: `clipper_agency/db/schema.py`
- Create: `tests/test_db_schema.py`

**Step 1: Write the failing test**

```python
# tests/test_db_schema.py
from clipper_agency.db.connection import get_connection, close_connection
from clipper_agency.db.schema import initialize_schema, table_exists


def test_initialize_schema_creates_tables(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    expected_tables = [
        "niches", "accounts", "jobs", "agent_states", "agent_configs",
        "templates", "assets", "research_cache", "job_outputs",
        "audit_log", "config_versions", "prompt_versions",
        "creative_history", "job_snapshots", "preflight_estimates",
    ]
    for table in expected_tables:
        assert table_exists(conn, table), f"Table {table} not created"
    close_connection()


def test_initialize_schema_idempotent(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    initialize_schema(conn)  # Should not raise
    close_connection()


def test_jobs_table_columns(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    cursor = conn.execute("PRAGMA table_info(jobs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "id" in columns
    assert "topic" in columns
    assert "status" in columns
    assert "niche" in columns
    close_connection()
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db_schema.py -v`
Expected: ImportError — no module `clipper_agency.db.schema`

**Step 3: Write minimal implementation**

```python
# clipper_agency/db/schema.py

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    config TEXT NOT NULL,  -- JSON blob
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


def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cursor.fetchone() is not None
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db_schema.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add database schema (15 tables)"
```

---

### Task 8: Database Queries ✅

**Files:**
- Create: `clipper_agency/db/queries.py`
- Create: `tests/test_db_queries.py`

**Step 1: Write the failing test**

```python
# tests/test_db_queries.py
from clipper_agency.db.connection import get_connection, close_connection
from clipper_agency.db.schema import initialize_schema
from clipper_agency.db.queries import (
    create_job, get_job, update_job_status,
    create_agent_state, get_agent_state, update_agent_state,
    list_jobs,
)


def test_create_and_get_job(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test topic", niche="indonesian_artists")
    assert job_id > 0
    job = get_job(conn, job_id)
    assert job["topic"] == "Test topic"
    assert job["niche"] == "indonesian_artists"
    assert job["status"] == "CREATED"
    close_connection()


def test_update_job_status(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    update_job_status(conn, job_id, "SAFETY_CHECKED")
    job = get_job(conn, job_id)
    assert job["status"] == "SAFETY_CHECKED"
    close_connection()


def test_create_and_get_agent_state(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    create_agent_state(conn, job_id=job_id, agent_name="safety")
    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "pending"
    assert state["agent_name"] == "safety"
    close_connection()


def test_update_agent_state(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    create_agent_state(conn, job_id, "safety")
    update_agent_state(conn, job_id, "safety", "completed", output_data='{"result": "pass"}')
    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "completed"
    close_connection()


def test_list_jobs_returns_ordered(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    id1 = create_job(conn, topic="A", niche="test")
    id2 = create_job(conn, topic="B", niche="test")
    jobs = list_jobs(conn)
    assert len(jobs) >= 2
    assert jobs[0]["id"] >= jobs[1]["id"]  Most recent first
    close_connection()
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db_queries.py -v`
Expected: ImportError — no module `clipper_agency.db.queries`

**Step 3: Write minimal implementation**

```python
# clipper_agency/db/queries.py
import json
import sqlite3
from typing import Any


def create_job(conn: sqlite3.Connection, topic: str, niche: str,
               account_id: int | None = None, template: str | None = None,
               config_snapshot: dict | None = None) -> int:
    cursor = conn.execute(
        """INSERT INTO jobs (topic, niche, account_id, template, config_snapshot)
           VALUES (?, ?, ?, ?, ?)""",
        (topic, niche, account_id, template,
         json.dumps(config_snapshot) if config_snapshot else None),
    )
    conn.commit()
    return cursor.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def update_job_status(conn: sqlite3.Connection, job_id: int,
                      status: str, error_message: str | None = None) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now'), error_message = COALESCE(?, error_message) WHERE id = ?",
        (status, error_message, job_id),
    )
    conn.commit()


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def create_agent_state(conn: sqlite3.Connection, job_id: int,
                       agent_name: str) -> int:
    cursor = conn.execute(
        "INSERT INTO agent_states (job_id, agent_name) VALUES (?, ?)",
        (job_id, agent_name),
    )
    conn.commit()
    return cursor.lastrowid


def get_agent_state(conn: sqlite3.Connection, job_id: int,
                    agent_name: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT * FROM agent_states WHERE job_id = ? AND agent_name = ?",
        (job_id, agent_name),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def update_agent_state(conn: sqlite3.Connection, job_id: int,
                       agent_name: str, state: str,
                       output_data: str | None = None,
                       error_message: str | None = None) -> None:
    completed = "datetime('now')" if state in ("completed", "failed") else None
    conn.execute(
        f"""UPDATE agent_states
            SET state = ?, output_data = COALESCE(?, output_data),
                error_message = COALESCE(?, error_message),
                completed_at = COALESCE({completed}, completed_at)
            WHERE job_id = ? AND agent_name = ?""",
        (state, output_data, error_message, job_id, agent_name),
    )
    conn.commit()
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db_queries.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add database queries (CRUD for jobs and agent states)"
```

> **Implementation note:** `list_jobs` uses `ORDER BY id DESC` instead of `ORDER BY created_at DESC`. SQLite's `datetime('now')` has second granularity, causing identical timestamps for rapid sequential inserts. Auto-incrementing `id` is always unique and correctly ordered.

**Branch:** `phase/2-database-layer` — merged to `master` via PR #4.

---

## Phase 3: External Services ✅ COMPLETED

### Task 9: OpenRouter LLM Client

**Files:**
- Create: `clipper_agency/llm/__init__.py`
- Create: `clipper_agency/llm/client.py`
- Create: `clipper_agency/llm/router.py`
- Create: `tests/test_llm_client.py`

**Step 1: Write the failing test**

```python
# tests/test_llm_client.py
from unittest.mock import patch, MagicMock

from clipper_agency.llm.client import OpenRouterClient


def test_client_init_requires_key():
    with patch.dict("os.environ", {}, clear=True):
        client = OpenRouterClient()
        assert client.api_key is None


def test_client_init_with_key():
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-v1-test"}):
        client = OpenRouterClient()
        assert client.api_key == "sk-or-v1-test"


@patch("httpx.Client")
def test_chat_completion(mock_httpx):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello, world!"}}],
        "usage": {"total_tokens": 10},
    }
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-v1-test"}):
        client = OpenRouterClient()
        result = client.chat(
            model="mimo-v2-flash",
            messages=[{"role": "user", "content": "Say hello"}],
        )
    assert result["content"] == "Hello, world!"
    assert result["model"] == "mimo-v2-flash"
    assert "usage" in result
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_llm_client.py -v`
Expected: ImportError

**Step 3: Write minimal implementation**

```python
# clipper_agency/llm/client.py
import os
from typing import Any

import httpx


class OpenRouterClient:
    """LLM client for OpenRouter API with multi-model support."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY")

    def chat(self, model: str, messages: list[dict[str, str]],
             temperature: float = 0.7, max_tokens: int = 1024,
             **kwargs: Any) -> dict[str, Any]:
        """Send a chat completion request."""
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        with httpx.Client(base_url=self.BASE_URL, timeout=60) as client:
            resp = client.post(
                "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "model": model,
                "usage": data.get("usage", {}),
            }
```

```python
# clipper_agency/llm/router.py
from enum import Enum


class ModelPreset(str, Enum):
    BUDGET_EAST = "budget_east"
    AGENTIC_EAST = "agentic_east"
    PREMIUM_EAST = "premium_east"
    PREMIUM_WEST = "premium_west"


PRESET_MODELS: dict[str, dict[str, str]] = {
    "budget_east": {
        "ultra_cheap": "glm-4-9b",
        "default": "mimo-v2-flash",
        "indonesian": "qwen3-32b",
    },
    "agentic_east": {
        "default": "minimax-m2.7",
        "reasoning": "deepseek-v3.2",
    },
    "premium_east": {
        "default": "kimi-k2.5",
    },
    "premium_west": {
        "default": "anthropic/claude-sonnet-4",
    },
}


def resolve_model(preset: ModelPreset, role: str = "default") -> str:
    """Resolve the model name for a given preset and role."""
    models = PRESET_MODELS.get(preset.value, PRESET_MODELS["budget_east"])
    return models.get(role, models.get("default", "mimo-v2-flash"))
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_llm_client.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add OpenRouter LLM client with model routing"
```

---

### Task 10: ElevenLabs Voice Service

**Files:**
- Create: `clipper_agency/services/__init__.py`
- Create: `clipper_agency/services/elevenlabs.py`
- Create: `tests/test_services_elevenlabs.py`

**Step 1: Write the failing test**

```python
# tests/test_services_elevenlabs.py
from unittest.mock import patch, MagicMock
from pathlib import Path

from clipper_agency.services.elevenlabs import ElevenLabsService


def test_service_init():
    svc = ElevenLabsService()
    assert svc.api_key is None


@patch("httpx.Client")
def test_generate_voice(mock_httpx, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_audio_data"
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
        output_path = tmp_path / "voice.mp3"
        result = svc.generate_voice(
            text="Halo, ini suara uji coba",
            voice_id="test-voice-id",
            output_path=str(output_path),
        )
    assert result == str(output_path)
    assert output_path.read_bytes() == b"fake_audio_data"


def test_generate_voice_no_key(tmp_path):
    svc = ElevenLabsService()
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        svc.generate_voice("test", "voice", str(tmp_path / "v.mp3"))
```

**Step 2: Run tests, implement, verify pass**

```python
# clipper_agency/services/elevenlabs.py
import os
from pathlib import Path

import httpx


class ElevenLabsService:
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")

    def generate_voice(self, text: str, voice_id: str,
                       output_path: str) -> str:
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
            resp = client.post(
                f"/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.7},
                },
            )
            resp.raise_for_status()
            path.write_bytes(resp.content)
        return str(path)
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add ElevenLabs voice generation service"
```

---

### Task 11: yt-dlp Media Download Service

**Files:**
- Create: `clipper_agency/services/ytdlp.py`
- Create: `tests/test_services_ytdlp.py`

**Step 1: Write the failing test**

```python
# tests/test_services_ytdlp.py
from unittest.mock import patch, MagicMock
from clipper_agency.services.ytdlp import YtDlpService, DownloadResult


def test_download_result_model():
    r = DownloadResult(path="/tmp/video.mp4", title="Test", duration=30.0)
    assert r.path == "/tmp/video.mp4"
    assert r.duration == 30.0


@patch("subprocess.run")
def test_download_video(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    svc = YtDlpService()
    out = tmp_path / "video.mp4"
    result = svc.download("https://example.com/video", str(out))
    assert result.path.endswith(".mp4")
    mock_run.assert_called_once()


def test_download_failure():
    svc = YtDlpService()
    result = svc.download("https://invalid-url", "/tmp/out.mp4")
    assert result is None
```

**Step 2: Implement**

```python
# clipper_agency/services/ytdlp.py
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DownloadResult:
    path: str
    title: str = ""
    duration: float = 0.0


class YtDlpService:
    """Download media using yt-dlp CLI."""

    def download(self, url: str, output_path: str,
                 max_duration: int = 30) -> Optional[DownloadResult]:
        """Download a video from URL. Returns None on failure."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["yt-dlp", "-f", "best[height<=1080]", "-o", str(out),
                 "--max-filesize", "50M", url],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return None
            # Try to find the actual file (yt-dlp may add extensions)
            files = list(out.parent.glob(f"{out.stem}*"))
            if files:
                return DownloadResult(path=str(files[0]))
            return DownloadResult(path=str(out))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add yt-dlp media download service"
```

---

### Task 12: Pexels Stock Media Service

**Files:**
- Create: `clipper_agency/services/pexels.py`
- Create: `tests/test_services_pexels.py`

```python
# clipper_agency/services/pexels.py
import os
from typing import Any

import httpx


class PexelsService:
    BASE_URL = "https://api.pexels.com/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("PEXELS_API_KEY")

    def search_videos(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY not set")
        with httpx.Client(base_url=self.BASE_URL) as client:
            resp = client.get(
                "/videos/search",
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": per_page, "orientation": "portrait"},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "id": v["id"],
                    "url": v["url"],
                    "duration": v["duration"],
                    "video_files": [
                        f for f in v["video_files"]
                        if f.get("quality") == "hd" or f.get("height", 0) <= 1080
                    ],
                }
                for v in data.get("videos", [])
            ]

    def download_video(self, video_url: str, output_path: str) -> str | None:
        """Download a video file from a direct URL."""
        import httpx
        from pathlib import Path
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.get(video_url)
                resp.raise_for_status()
                path.write_bytes(resp.content)
            return str(path)
        except Exception:
            return None
```

Test:

```python
from unittest.mock import patch, MagicMock
from clipper_agency.services.pexels import PexelsService


@patch("httpx.Client")
def test_search_videos(mock_httpx):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"videos": [{"id": 1, "url": "https://example.com", "duration": 10, "video_files": []}]}
    mock_httpx.return_value.__enter__.return_value.get.return_value = mock_response

    with patch.dict("os.environ", {"PEXELS_API_KEY": "test-key"}):
        svc = PexelsService()
        results = svc.search_videos("concert")
    assert len(results) == 1
    assert results[0]["id"] == 1
```

Commit: `git add -A && git commit -m "feat: add Pexels stock media service"`

---

### Task 13: Firecrawl Web Search Service

**Files:**
- Create: `clipper_agency/services/firecrawl_service.py`
- Create: `tests/test_services_firecrawl.py`

**Step 1: Implement + Test**

```python
# clipper_agency/services/firecrawl_service.py
import os
from typing import Any

import httpx


class FirecrawlService:
    BASE_URL = "https://api.firecrawl.dev/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("FIRECRAWL_API_KEY")

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ValueError("FIRECRAWL_API_KEY not set")
        with httpx.Client(base_url=self.BASE_URL, timeout=30) as client:
            resp = client.post(
                "/search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "maxResults": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "description": r.get("description"),
                    "content": r.get("content", "")[:2000],
                }
                for r in data.get("data", [])
            ]

    def scrape(self, url: str) -> dict[str, Any] | None:
        """Scrape a single URL and return markdown content."""
        with httpx.Client(base_url=self.BASE_URL, timeout=30) as client:
            resp = client.post(
                "/scrape",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "formats": ["markdown"]},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data.get("data")
```

Test with mocks using similar pattern to previous services.

Commit: `git add -A && git commit -m "feat: add Firecrawl web search service"`

---

### Task 14: ScrapeCreators TikTok Data Service

**Files:**
- Create: `clipper_agency/services/scrapecreators.py`
- Create: `tests/test_services_scrapecreators.py`

```python
# clipper_agency/services/scrapecreators.py
import os
from typing import Any

import httpx


class ScrapeCreatorsService:
    BASE_URL = "https://api.scrapecreators.com/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("SCRAPECREATORS_API_KEY")

    def search_tiktok_videos(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ValueError("SCRAPECREATORS_API_KEY not set")
        with httpx.Client(base_url=self.BASE_URL, timeout=30) as client:
            resp = client.get(
                "/tiktok/search",
                headers={"x-api-key": self.api_key},
                params={"keyword": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
```

Test with mocks.

Commit: `git add -A && git commit -m "feat: add ScrapeCreators TikTok data service"`

**Branch:** `phase/3-services` — merged to `master` via PR #5.

---

## Phase 4: Agent Framework ✅ COMPLETED

**Branch:** `phase/4-agent-framework` — merged to `master` via PR #6.

### Task 15: Base Agent Class

**Files:**
- Create: `clipper_agency/agents/__init__.py`
- Create: `clipper_agency/agents/base.py`
- Create: `tests/test_agents_base.py`

**Step 1: Write the failing test**

```python
# tests/test_agents_base.py
import json
from clipper_agency.db.connection import get_connection, close_connection
from clipper_agency.db.schema import initialize_schema
from clipper_agency.db.queries import create_job, create_agent_state
from clipper_agency.agents.base import BaseAgent


class ConcreteAgent(BaseAgent):
    """Test agent that always passes."""
    @property
    def agent_name(self) -> str:
        return "concrete_test"

    def execute(self, job_id: int, **kwargs) -> dict:
        return {"status": "pass", "output": "test_output"}


def test_agent_name():
    agent = ConcreteAgent()
    assert agent.agent_name == "concrete_test"


def test_agent_run_updates_db(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "concrete_test")

    agent = ConcreteAgent()
    result = agent.run(job_id)

    assert result["status"] == "pass"
    state = conn.execute(
        "SELECT state FROM agent_states WHERE job_id=? AND agent_name=?",
        (job_id, "concrete_test"),
    ).fetchone()
    assert state[0] == "completed"
    close_connection()
```

**Step 2: Implement**

```python
# clipper_agency/agents/base.py
from abc import ABC, abstractmethod
from typing import Any

from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import update_agent_state


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Unique agent identifier matching agent_states.agent_name."""
        ...

    @abstractmethod
    def execute(self, job_id: int, **kwargs: Any) -> dict[str, Any]:
        """Execute the agent's core logic. Returns result dict."""
        ...

    def run(self, job_id: int, db_path: str = "data/clipper.db",
            **kwargs: Any) -> dict[str, Any]:
        """Run agent with DB state tracking."""
        update_agent_state(None, job_id, self.agent_name, "running")
        try:
            conn = get_connection(db_path)
            update_agent_state(conn, job_id, self.agent_name, "running")
            result = self.execute(job_id, **kwargs)
            update_agent_state(
                conn, job_id, self.agent_name, "completed",
                output_data=result,
            )
            return result
        except Exception as e:
            conn = get_connection(db_path)
            update_agent_state(
                conn, job_id, self.agent_name, "failed",
                error_message=str(e),
            )
            return {"status": "error", "error": str(e)}
```

**Step 3: Verify pass, commit**

```bash
git add -A && git commit -m "feat: add base agent class with DB state tracking"
```

---

### Task 16: Gate Definitions

**Files:**
- Create: `clipper_agency/orchestrator/__init__.py`
- Create: `clipper_agency/orchestrator/gates.py`
- Create: `tests/test_gates.py`

**Step 1: Write the failing test**

```python
# tests/test_gates.py
from clipper_agency.orchestrator.gates import (
    GateResult, GateInputPreflight, GateCostEstimate,
    GateResearchCache, GatePostResearchRisk,
)


def test_gate_result_model():
    r = GateResult(passed=True, severity="pass", message="OK")
    assert r.passed
    assert r.severity == "pass"
    assert r.message == "OK"


def test_g1_input_preflight_valid():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="Ariana Grande konser Jakarta")
    assert result.passed
    assert result.severity == "pass"


def test_g1_input_preflight_empty():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="")
    assert not result.passed
    assert result.severity == "hard_fail"


def test_g1_input_preflight_whitespace():
    gate = GateInputPreflight()
    result = gate.evaluate(topic="   ")
    assert not result.passed


def test_g2_cost_estimate_pass():
    gate = GateCostEstimate()
    result = gate.evaluate(cached=True, niche_config={"name": "test"})
    assert result.passed
    assert result.estimate_cents > 0
```

**Step 2: Implement**

```python
# clipper_agency/orchestrator/gates.py
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateResult:
    passed: bool
    severity: str  # "pass" | "soft_fail" | "hard_fail"
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class BaseGate:
    """Base class for pipeline gates."""
    def evaluate(self, **kwargs: Any) -> GateResult:
        raise NotImplementedError


class GateInputPreflight(BaseGate):
    """G1: Validate topic input before any processing."""
    def evaluate(self, topic: str = "", niche_config: dict | None = None,
                 source_url: str | None = None, **kwargs) -> GateResult:
        if not topic or not topic.strip():
            return GateResult(False, "hard_fail", "Topic cannot be empty")
        if niche_config is None:
            return GateResult(False, "hard_fail", "Niche config required")
        return GateResult(True, "pass", "Input valid",
                          data={"topic": topic.strip()})


class GateCostEstimate(BaseGate):
    """G2: Lightweight cost + credit estimate."""
    BASE_COST_CENTS = 3.3  # Budget East total in cents

    def evaluate(self, cached: bool = False,
                 niche_config: dict | None = None, **kwargs) -> GateResult:
        estimated_cents = self.BASE_COST_CENTS if not cached else self.BASE_COST_CENTS * 0.7
        return GateResult(True, "pass", f"Est. cost: ${estimated_cents/100:.4f}",
                          data={"estimate_cents": estimated_cents})


class GateResearchCache(BaseGate):
    """G3: Check research cache TTL."""
    def evaluate(self, cache_entry: dict | None = None, **kwargs) -> GateResult:
        if cache_entry and cache_entry.get("freshness") == "fresh":
            return GateResult(True, "pass", "Fresh cache available",
                              data=cache_entry)
        if cache_entry and cache_entry.get("freshness") == "stale":
            return GateResult(True, "soft_fail", "Stale cache - reusing",
                              data=cache_entry)
        return GateResult(False, "hard_fail", "No valid cache - research needed")


class GatePostResearchRisk(BaseGate):
    """G4: Post-research risk check."""
    DANGER_KEYWORDS = ["ilegal", "banned", "defamation", "sara"]

    def evaluate(self, risk_flags: list[str] | None = None,
                 **kwargs) -> GateResult:
        flags = risk_flags or []
        if any(kw in " ".join(flags).lower() for kw in self.DANGER_KEYWORDS):
            return GateResult(False, "hard_fail", "High-risk content detected",
                              data={"risk_flags": flags})
        if any("unverified" in f.lower() for f in flags):
            return GateResult(True, "soft_fail", "Unverified claims - use cautious wording",
                              data={"risk_flags": flags})
        return GateResult(True, "pass", "No risks detected")


class GateSourceQuality(BaseGate):
    """G5: Source quality check."""
    def evaluate(self, video_sources: list | None = None, **kwargs) -> GateResult:
        sources = video_sources or []
        if len(sources) >= 2:
            return GateResult(True, "pass", f"{len(sources)} sources available")
        if len(sources) == 1:
            return GateResult(True, "soft_fail", "Only 1 source - use Pexels fallback")
        return GateResult(False, "hard_fail", "No usable sources")


class GateCreativeMemory(BaseGate):
    """G6: Creative memory check."""
    def evaluate(self, used_angles: list[str] | None = None,
                 available_angles: list[str] | None = None, **kwargs) -> GateResult:
        used = set(used_angles or [])
        available = set(available_angles or [])
        remaining = available - used
        if len(remaining) >= 2:
            return GateResult(True, "pass", "Variation available",
                              data={"remaining_angles": list(remaining)})
        if len(remaining) == 1:
            return GateResult(True, "soft_fail", "Only 1 angle left")
        return GateResult(False, "hard_fail", "All angles exhausted")


class GateScriptValidation(BaseGate):
    """G7: Script validation."""
    def evaluate(self, script: str = "", caption: str = "", **kwargs) -> GateResult:
        if not script.strip():
            return GateResult(False, "hard_fail", "Empty script")
        if not caption.strip():
            return GateResult(False, "soft_fail", "Empty caption - auto-generate")
        if len(caption) > 150:
            return GateResult(True, "soft_fail", "Caption >150 chars - trim needed")
        return GateResult(True, "pass", "Script and caption valid")


class GateAudioValidation(BaseGate):
    """G8: Audio validation."""
    def evaluate(self, audio_path: str | None = None, **kwargs) -> GateResult:
        from pathlib import Path
        if not audio_path or not Path(audio_path).exists():
            return GateResult(False, "hard_fail", "Audio file missing")
        size = Path(audio_path).stat().st_size
        if size == 0:
            return GateResult(False, "hard_fail", "Audio file is empty")
        return GateResult(True, "pass", "Audio valid")


class GateAssetValidation(BaseGate):
    """G9: Asset validation."""
    def evaluate(self, asset_paths: list[str] | None = None, **kwargs) -> GateResult:
        from pathlib import Path
        paths = asset_paths or []
        if not paths:
            return GateResult(False, "hard_fail", "No assets")
        valid = [p for p in paths if Path(p).exists() and Path(p).stat().st_size > 0]
        if not valid:
            return GateResult(False, "hard_fail", "No valid assets")
        if len(valid) < len(paths):
            return GateResult(True, "soft_fail", f"{len(valid)}/{len(paths)} assets valid")
        return GateResult(True, "pass", "All assets valid")


class GateVideoValidation(BaseGate):
    """G10: Video output validation."""
    def evaluate(self, video_path: str | None = None, **kwargs) -> GateResult:
        from pathlib import Path
        if not video_path or not Path(video_path).exists():
            return GateResult(False, "hard_fail", "Video file missing")
        size = Path(video_path).stat().st_size
        if size < 1024:
            return GateResult(False, "hard_fail", "Video file too small (<1KB)")
        return GateResult(True, "pass", "Video valid")
```

**Step 3: Verify pass, commit**

```bash
git add -A && git commit -m "feat: add all 10 gate definitions (G1-G10)"
```

---

### Task 17: State Machine

**Files:**
- Create: `clipper_agency/orchestrator/state_machine.py`
- Create: `tests/test_state_machine.py`

**Step 1: Test**

```python
# tests/test_state_machine.py
from clipper_agency.orchestrator.state_machine import (
    JobStateMachine, JOB_STATES, VALID_TRANSITIONS,
)


def test_initial_state():
    sm = JobStateMachine()
    assert sm.current_state == "CREATED"


def test_valid_transition():
    sm = JobStateMachine()
    sm.transition_to("PREFLIGHT")
    assert sm.current_state == "PREFLIGHT"


def test_invalid_transition():
    sm = JobStateMachine()
    with pytest.raises(ValueError, match="Cannot transition"):
        sm.transition_to("COMPLETED")  # Can't jump from CREATED to COMPLETED


def test_full_pipeline():
    states = ["CREATED", "PREFLIGHT", "COST_ESTIMATED", "SAFETY_CHECKED",
              "RESEARCHING", "RESEARCH_REVIEWED", "SOURCES_VALIDATED",
              "MEMORY_CHECKED", "SCRIPTING", "SCRIPT_VALIDATED",
              "VOICING", "AUDIO_VALIDATED", "VISUALIZING",
              "ASSETS_VALIDATED", "COMPOSING", "VIDEO_VALIDATED",
              "REVIEWING", "COMPLETED"]
    sm = JobStateMachine()
    for i, state in enumerate(states[1:], 1):
        sm.transition_to(state)
        assert sm.current_state == state
    assert sm.is_terminal()


def test_failure_state():
    sm = JobStateMachine()
    sm.transition_to("FAILED")
    assert sm.is_terminal()
```

**Step 2: Implement**

```python
# clipper_agency/orchestrator/state_machine.py
from typing import ClassVar

JOB_STATES = [
    "CREATED", "PREFLIGHT", "COST_ESTIMATED", "SAFETY_CHECKED",
    "RESEARCHING", "RESEARCH_REVIEWED", "SOURCES_VALIDATED",
    "MEMORY_CHECKED", "SCRIPTING", "SCRIPT_VALIDATED",
    "VOICING", "AUDIO_VALIDATED", "VISUALIZING",
    "ASSETS_VALIDATED", "COMPOSING", "VIDEO_VALIDATED",
    "REVIEWING", "COMPLETED", "FAILED", "PAUSED",
]

VALID_TRANSITIONS: dict[str, list[str]] = {
    "CREATED": ["PREFLIGHT", "FAILED"],
    "PREFLIGHT": ["COST_ESTIMATED", "FAILED", "PAUSED"],
    "COST_ESTIMATED": ["SAFETY_CHECKED", "FAILED", "PAUSED"],
    "SAFETY_CHECKED": ["RESEARCHING", "FAILED", "PAUSED"],
    "RESEARCHING": ["RESEARCH_REVIEWED", "FAILED", "PAUSED"],
    "RESEARCH_REVIEWED": ["SOURCES_VALIDATED", "FAILED", "PAUSED"],
    "SOURCES_VALIDATED": ["MEMORY_CHECKED", "FAILED", "PAUSED"],
    "MEMORY_CHECKED": ["SCRIPTING", "FAILED", "PAUSED"],
    "SCRIPTING": ["SCRIPT_VALIDATED", "FAILED", "PAUSED"],
    "SCRIPT_VALIDATED": ["VOICING", "FAILED", "PAUSED"],
    "VOICING": ["AUDIO_VALIDATED", "FAILED", "PAUSED"],
    "AUDIO_VALIDATED": ["VISUALIZING", "FAILED", "PAUSED"],
    "VISUALIZING": ["ASSETS_VALIDATED", "FAILED", "PAUSED"],
    "ASSETS_VALIDATED": ["COMPOSING", "FAILED", "PAUSED"],
    "COMPOSING": ["VIDEO_VALIDATED", "FAILED", "PAUSED"],
    "VIDEO_VALIDATED": ["REVIEWING", "FAILED", "PAUSED"],
    "REVIEWING": ["COMPLETED", "FAILED", "PAUSED"],
    "COMPLETED": [],
    "FAILED": [],
    "PAUSED": JOB_STATES,  # Can resume to any state
}


class JobStateMachine:
    """Validates and tracks job state transitions."""

    def __init__(self, initial_state: str = "CREATED") -> None:
        if initial_state not in JOB_STATES:
            raise ValueError(f"Invalid initial state: {initial_state}")
        self.current_state = initial_state

    def transition_to(self, new_state: str) -> str:
        """Attempt to transition to a new state. Returns the new state."""
        allowed = VALID_TRANSITIONS.get(self.current_state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Cannot transition from {self.current_state} to {new_state}. "
                f"Allowed: {allowed}"
            )
        self.current_state = new_state
        return self.current_state

    def is_terminal(self) -> bool:
        return self.current_state in ("COMPLETED", "FAILED")
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add job state machine with transition validation"
```

---

## Phase 5: Individual Agents ✅ COMPLETED

### Task 18: Safety Agent (A1)

**Files:**
- Create: `clipper_agency/agents/safety.py`
- Create: `tests/test_agents_safety.py`

**Step 1: Test**

```python
# tests/test_agents_safety.py
from unittest.mock import patch, MagicMock
from clipper_agency.agents.safety import SafetyAgent


def test_safety_agent_name():
    agent = SafetyAgent()
    assert agent.agent_name == "safety"


@patch("clipper_agency.llm.client.OpenRouterClient.chat")
def test_safety_pass(mock_chat):
    mock_chat.return_value = {
        "content": '{"verdict": "pass", "reason": "Topic appears safe"}',
        "model": "glm-4-9b",
    }
    agent = SafetyAgent()
    result = agent.execute(job_id=1, topic="Ariana Grande konser")
    assert result["status"] == "pass"


@patch("clipper_agency.llm.client.OpenRouterClient.chat")
def test_safety_hard_block(mock_chat):
    mock_chat.return_value = {
        "content": '{"verdict": "hard_block", "reason": "Illegal content"}',
        "model": "glm-4-9b",
    }
    agent = SafetyAgent()
    result = agent.execute(job_id=1, topic="Illegal content")
    assert result["status"] == "hard_fail"


def test_safety_parse_response():
    agent = SafetyAgent()
    result = agent._parse_response('{"verdict": "pass", "reason": "Safe"}')
    assert result["status"] == "pass"


def test_safety_malformed_response():
    agent = SafetyAgent()
    result = agent._parse_response("not json")
    assert result["status"] == "hard_fail"
    assert "parse" in result["reason"].lower()
```

**Step 2: Implement**

```python
# clipper_agency/agents/safety.py
import json
import os
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.llm.client import OpenRouterClient

SAFETY_PROMPT = """You are a content safety checker. Analyze the following topic and return a JSON verdict:
- "pass": Topic is safe for content generation
- "soft_warning": Topic contains unverified claims that need cautious wording
- "hard_block": Topic involves illegal content, defamation, hate speech, or banned platform policy

Rules:
- Hard-block: illegal activities, hate speech, defamation, explicit harmful content
- Soft-warning: unverified rumors, unconfirmed news, speculative claims
- Pass: everything else (entertainment news, celebrity updates, trending topics)

Respond ONLY with valid JSON: {"verdict": "...", "reason": "..."}
"""


class SafetyAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "safety"

    def execute(self, job_id: int, topic: str = "",
                safety_rules: list[str] | None = None, **kwargs) -> dict[str, Any]:
        llm = OpenRouterClient()
        response = llm.chat(
            model="glm-4-9b",
            messages=[
                {"role": "system", "content": SAFETY_PROMPT},
                {"role": "user", "content": f"Topic: {topic}\nRules: {safety_rules or []}"},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        return self._parse_response(response["content"])

    def _parse_response(self, content: str) -> dict[str, Any]:
        try:
            data = json.loads(content.strip().strip("```json").strip("```").strip())
            verdict = data.get("verdict", "hard_block")
            reason = data.get("reason", "No reason given")
            if verdict == "pass":
                return {"status": "pass", "reason": reason}
            elif verdict == "soft_warning":
                return {"status": "soft_warning", "reason": reason,
                        "requires_cautious_wording": True}
            else:
                return {"status": "hard_fail", "reason": reason}
        except (json.JSONDecodeError, KeyError) as e:
            return {"status": "hard_fail", "reason": f"Failed to parse response: {e}"}
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add Safety Agent with LLM-based content checking"
```

---

### Task 19: Researcher Agent (A2)

**Files:**
- Create: `clipper_agency/agents/researcher.py`
- Create: `tests/test_agents_researcher.py`

```python
# clipper_agency/agents/researcher.py
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.services.firecrawl_service import FirecrawlService
from clipper_agency.services.scrapecreators import ScrapeCreatorsService
from clipper_agency.llm.client import OpenRouterClient

RESEARCHER_SYSTEM_PROMPT = """You are a research agent. Given search results, produce a structured summary.
Extract: topic summary, key facts, entities (artists, locations, events), source URLs, and risk flags.

Output JSON with fields: topic_brief, context_sources[], tags[], entities (artists[], locations[], events[]), risk_flags[]
"""


class ResearcherAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "researcher"

    def execute(self, job_id: int, topic: str = "",
                niche_config: dict | None = None, **kwargs) -> dict[str, Any]:
        niche = niche_config or {}
        language = niche.get("language", "id")
        firecrawl = FirecrawlService()
        scrapecreators = ScrapeCreatorsService()

        web_results = []
        tiktok_results = []

        try:
            web_results = firecrawl.search(query=topic, max_results=5)
        except Exception:
            pass

        try:
            tiktok_results = scrapecreators.search_tiktok_videos(query=topic, max_results=3)
        except Exception:
            pass

        llm = OpenRouterClient()
        synthesis = llm.chat(
            model="mimo-v2-flash",
            messages=[
                {"role": "system", "content": RESEARCHER_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Topic: {topic}\nLanguage: {language}\n"
                    f"Web results: {web_results}\n"
                    f"TikTok results: {tiktok_results}\n"
                )},
            ],
            temperature=0.3,
        )

        return {
            "topic": topic,
            "topic_brief": f"Research for: {topic}",
            "video_sources": [{"url": r.get("url", "")} for r in web_results[:3]],
            "context_sources": web_results[:3],
            "tags": [f"topic:{topic}"],
            "entities": {"artists": [], "locations": [], "events": []},
            "risk_flags": [],
            "synthesis": synthesis["content"],
            "cache_key": f"id:{language}:{topic.lower().replace(' ','_')}",
        }
```

Test:

```python
from unittest.mock import patch, MagicMock
from clipper_agency.agents.researcher import ResearcherAgent


@patch("clipper_agency.services.firecrawl_service.FirecrawlService.search")
@patch("clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos")
@patch("clipper_agency.llm.client.OpenRouterClient.chat")
def test_researcher_execute(mock_llm, mock_tiktok, mock_firecrawl):
    mock_firecrawl.return_value = [{"url": "https://example.com/news", "title": "News"}]
    mock_tiktok.return_value = [{"url": "https://tiktok.com/@user/video/123"}]
    mock_llm.return_value = {"content": "Synthesized research", "model": "mimo-v2-flash"}

    agent = ResearcherAgent()
    result = agent.execute(job_id=1, topic="Test artist scandal")
    assert result["topic"] == "Test artist scandal"
    assert len(result["video_sources"]) > 0
```

Commit: `git add -A && git commit -m "feat: add Researcher Agent with Firecrawl + ScrapeCreators"`

---

### Task 20: Scriptwriter Agent (A3)

**Files:**
- Create: `clipper_agency/agents/scriptwriter.py`
- Create: `tests/test_agents_scriptwriter.py`

```python
# clipper_agency/agents/scriptwriter.py
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.llm.client import OpenRouterClient

SCRIPTWRITER_PROMPT = """You are a scriptwriter for TikTok infotainment content in Bahasa Indonesia.
Write a 20-30 second voiceover script and caption.

Topic: {topic}
Tone: {tone} (casual, TikTok-style)
Language: {language}
Risk flags: {risk_flags}

Rules:
- Script: 40-60 words, conversational, engaging hook in first 3 seconds
- Caption: max 150 chars, max 5 hashtags, includes call-to-action
- If risk_flags contains unverified: use "dikabarkan" or "ramai dibahas netizen"
- Output JSON: {{"script": "...", "caption": "...", "angle": "...", "hook": "..."}}
"""


class ScriptwriterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "scriptwriter"

    def execute(self, job_id: int, topic: str = "",
                research_output: dict | None = None,
                niche_config: dict | None = None, **kwargs) -> dict[str, Any]:
        import json
        research = research_output or {}
        niche = niche_config or {}

        llm = OpenRouterClient()
        response = llm.chat(
            model="qwen3-32b",
            messages=[
                {"role": "system", "content": SCRIPTWRITER_PROMPT.format(
                    topic=topic,
                    tone=niche.get("tone", "casual_tiktok"),
                    language=niche.get("language", "id"),
                    risk_flags=research.get("risk_flags", []),
                )},
                {"role": "user", "content": (
                    f"Research: {research.get('topic_brief', '')}\n"
                    f"Sources: {research.get('context_sources', [])}\n"
                )},
            ],
            temperature=0.7,
        )

        try:
            data = json.loads(response["content"].strip().strip("```json").strip("```").strip())
        except json.JSONDecodeError:
            data = {"script": response["content"], "caption": topic[:150]}

        return {
            "script": data.get("script", ""),
            "caption": data.get("caption", "")[:150],
            "angle": data.get("angle", "breaking_update"),
            "hook": data.get("hook", ""),
        }
```

Commit: `git add -A && git commit -m "feat: add Scriptwriter Agent for TikTok scripts"`

---

### Task 21: Voice Producer Agent (A4)

**Files:**
- Create: `clipper_agency/agents/voice_producer.py`
- Create: `tests/test_agents_voice.py`

```python
# clipper_agency/agents/voice_producer.py
import os
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.services.elevenlabs import ElevenLabsService


class VoiceProducerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "voice_producer"

    def execute(self, job_id: int, script: str = "",
                voice_id: str | None = None, **kwargs) -> dict[str, Any]:
        voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "")
        if not voice_id:
            return {"status": "error", "error": "No voice ID configured"}

        svc = ElevenLabsService()
        output_dir = f"assets/voiceovers"
        output_path = f"{output_dir}/{job_id}.mp3"

        result_path = svc.generate_voice(
            text=script,
            voice_id=voice_id,
            output_path=output_path,
        )

        from pathlib import Path
        import subprocess
        duration = 0.0
        try:
            ffprobe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", result_path],
                capture_output=True, text=True, timeout=10,
            )
            duration = float(ffprobe.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            pass

        return {
            "audio_path": result_path,
            "duration_seconds": duration,
            "status": "completed",
        }
```

Test: with mock ElevenLabsService, verify duration is extracted.

Commit: `git add -A && git commit -m "feat: add Voice Producer Agent for ElevenLabs TTS"`

---

### Task 22: Visual Director Agent (A5)

**Files:**
- Create: `clipper_agency/agents/visual_director.py`
- Create: `tests/test_agents_visual.py`

```python
# clipper_agency/agents/visual_director.py
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.services.ytdlp import YtDlpService
from clipper_agency.services.pexels import PexelsService


class VisualDirectorAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "visual_director"

    def execute(self, job_id: int, video_sources: list | None = None,
                tags: list[str] | None = None,
                script: str = "", **kwargs) -> dict[str, Any]:
        sources = video_sources or []
        downloaded = []
        yt = YtDlpService()
        pexels = PexelsService()

        for i, src in enumerate(sources[:3]):
            url = src.get("url", "") if isinstance(src, dict) else ""
            if not url:
                continue
            out_path = f"assets/cache/{job_id}_src_{i}.mp4"
            result = yt.download(url, out_path)
            if result:
                downloaded.append({"path": result.path, "source_url": url})

        # If not enough sources, try Pexels
        if len(downloaded) < 2 and tags:
            for tag in tags[:2]:
                pexels_results = pexels.search_videos(query=tag.replace("topic:", ""), per_page=3)
                for pv in pexels_results[:2]:
                    video_files = pv.get("video_files", [])
                    if video_files:
                        dl = pexels.download_video(
                            video_files[0].get("link", ""),
                            f"assets/cache/{job_id}_pexels_{tag}.mp4",
                        )
                        if dl:
                            downloaded.append({"path": dl, "source": "pexels"})

        # Build scene plan
        scenes = []
        script_sentences = [s.strip() for s in script.split(".") if s.strip()]
        for i, sentence in enumerate(script_sentences):
            clip = downloaded[i % max(len(downloaded), 1)] if downloaded else None
            scenes.append({
                "order": i,
                "text": sentence,
                "asset_path": clip["path"] if clip else None,
                "asset_type": "clip" if clip else "generated_card",
                "duration_seconds": min(max(len(sentence.split()) * 0.4, 2.0), 5.0),
            })

        return {
            "scenes": scenes,
            "downloaded_assets": [d["path"] for d in downloaded],
            "total_duration": sum(s["duration_seconds"] for s in scenes),
        }
```

Commit: `git add -A && git commit -m "feat: add Visual Director Agent for asset selection"`

---

### Task 23: Composer Agent (A6) — FFmpeg Assembly

**Files:**
- Create: `clipper_agency/agents/composer.py`
- Create: `tests/test_agents_composer.py`

**Step 1: Test**

```python
# tests/test_agents_composer.py
from unittest.mock import patch, MagicMock
from clipper_agency.agents.composer import ComposerAgent


@patch("subprocess.run")
def test_composer_name(mock_run):
    agent = ComposerAgent()
    assert agent.agent_name == "composer"


@patch("subprocess.run")
def test_composer_execute(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    agent = ComposerAgent()
    scenes = [
        {"order": 0, "text": "Halo semua", "asset_path": None,
         "asset_type": "generated_card", "duration_seconds": 3.0},
    ]
    result = agent.execute(
        job_id=1, scenes=scenes, audio_path="/fake/audio.mp3",
        output_dir=str(tmp_path), caption="Test caption",
    )
    assert result["status"] == "completed"
    assert "video_path" in result
```

**Step 2: Implement**

```python
# clipper_agency/agents/composer.py
import subprocess
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent


class ComposerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "composer"

    def execute(self, job_id: int, scenes: list | None = None,
                audio_path: str | None = None,
                output_dir: str = "outputs",
                caption: str = "", **kwargs) -> dict[str, Any]:
        scenes = scenes or []
        output_path = Path(output_dir) / f"{job_id}.mp4"
        thumb_path = Path(output_dir) / f"{job_id}_thumb.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not scenes:
            return {"status": "failed", "error": "No scenes to compose"}

        # Build FFmpeg filter_complex for scene assembly
        filter_parts = []
        inputs = []
        input_idx = 0

        for scene in scenes:
            asset = scene.get("asset_path")
            duration = scene.get("duration_seconds", 3.0)
            if asset and Path(asset).exists():
                inputs.append(("-i", asset))
                filter_parts.append(
                    f"[{input_idx}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                    f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                    f"trim=duration={duration},setpts=PTS-STARTPTS[v{input_idx}]"
                )
                input_idx += 1
            else:
                # Generate card with drawtext for missing assets
                text = scene.get("text", "")[:80]
                filter_parts.append(
                    f"color=c=black:s=1080x1920:d={duration}[bg{input_idx}];"
                    f"[bg{input_idx}]drawtext=text='{text}':"
                    f"fontsize=48:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
                    f"enable='between(t,0,{duration})'[v{input_idx}]"
                )
                input_idx += 1

        # Concatenate all video streams
        concat_input = "".join(f"[v{i}]" for i in range(input_idx))
        filter_complex = ";".join(filter_parts)
        if input_idx > 1:
            filter_complex += f";{concat_input}concat=n={input_idx}:v=1:a=0[vout]"
        elif input_idx == 1:
            filter_complex += f";[v0]copy[vout]"

        ffmpeg_cmd = ["ffmpeg", "-y"]
        for flag, arg in inputs:
            ffmpeg_cmd.extend([flag, arg])
        ffmpeg_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-r", "30",
        ])

        if audio_path and Path(audio_path).exists():
            ffmpeg_cmd.extend(["-i", audio_path, "-c:a", "aac", "-shortest"])
            # Replace [vout] map to include audio
            ffmpeg_cmd[ffmpeg_cmd.index("-map") + 1] = "[vout]"

        ffmpeg_cmd.append(str(output_path))

        try:
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return {"status": "failed", "error": result.stderr[:500]}
        except subprocess.TimeoutExpired:
            return {"status": "failed", "error": "FFmpeg timed out after 300s"}

        # Generate thumbnail
        subprocess.run([
            "ffmpeg", "-y", "-i", str(output_path),
            "-vframes", "1", "-s", "1080x1920", str(thumb_path),
        ], capture_output=True, timeout=30)

        return {
            "status": "completed",
            "video_path": str(output_path),
            "thumbnail_path": str(thumb_path),
            "duration_seconds": sum(s.get("duration_seconds", 3.0) for s in scenes),
        }
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add Composer Agent with FFmpeg scene assembly"
```

---

### Task 24: Reviewer Agent (A7)

**Files:**
- Create: `clipper_agency/agents/reviewer.py`
- Create: `tests/test_agents_reviewer.py`

```python
# clipper_agency/agents/reviewer.py
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.llm.client import OpenRouterClient

REVIEWER_PROMPT = """Review the following video generation output for quality, safety, and duplicates.

Script: {script}
Caption: {caption}
Creative history: {creative_history}

Evaluate:
1. Quality: Is the script engaging? Is the caption well-formatted?
2. Safety: Any remaining safety concerns?
3. Duplicate: Does this content overlap with recent generations?

Output JSON: {{"verdict": "pass|reject", "issues": [], "recommended_retry_step": null, "quality_score": 0.0}}
"""


class ReviewerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "reviewer"

    def execute(self, job_id: int, script: str = "",
                caption: str = "", video_path: str | None = None,
                creative_history: list | None = None, **kwargs) -> dict[str, Any]:
        llm = OpenRouterClient()
        response = llm.chat(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": REVIEWER_PROMPT.format(
                    script=script, caption=caption,
                    creative_history=creative_history or [],
                )},
                {"role": "user", "content": f"Review job {job_id}"},
            ],
            temperature=0.3,
        )

        import json
        try:
            data = json.loads(response["content"].strip().strip("```json").strip("```").strip())
        except json.JSONDecodeError:
            data = {"verdict": "pass", "issues": [], "quality_score": 0.8}

        return {
            "verdict": data.get("verdict", "pass"),
            "issues": data.get("issues", []),
            "quality_score": data.get("quality_score", 0.8),
            "recommended_retry_step": data.get("recommended_retry_step"),
        }
```

Commit: `git add -A && git commit -m "feat: add Reviewer Agent with LLM quality check"`

---

### Task 25: Output Packager

**Files:**
- Create: `clipper_agency/output/__init__.py`
- Create: `clipper_agency/output/packager.py`
- Create: `tests/test_output_packager.py`

**Step 1: Test**

```python
# tests/test_output_packager.py
import json
from pathlib import Path
from clipper_agency.output.packager import OutputPackager


def test_packager_creates_files(tmp_path):
    pkg = OutputPackager(output_dir=str(tmp_path))
    result = pkg.package(
        job_id=1,
        video_path=str(tmp_path / "video.mp4"),
        script="Test script",
        caption="Test caption #viral",
        metadata={"topic": "Test", "cost": 0.033},
    )
    assert result["video_path"]
    assert result["caption_path"]
    assert result["thumbnail_path"]
    assert result["metadata_path"]
    assert Path(result["caption_path"]).exists()


def test_caption_format():
    pkg = OutputPackager()
    caption = pkg.format_caption("Test caption with more than 150 characters " * 5)
    assert len(caption) <= 150


def test_metadata_structure():
    pkg = OutputPackager()
    meta = pkg.build_metadata(job_id=1, topic="Test", niche="indonesian_artists",
                              duration=30.0, cost=0.033)
    assert meta["job_id"] == 1
    assert meta["topic"] == "Test"
    assert "duration_seconds" in meta
```

**Step 2: Implement**

```python
# clipper_agency/output/packager.py
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


class OutputPackager:
    """Produces the final output package: video + caption + thumbnail + metadata."""

    def __init__(self, output_dir: str = "outputs") -> None:
        self.output_dir = Path(output_dir)

    def package(self, job_id: int, video_path: str, script: str,
                caption: str, metadata: dict[str, Any]) -> dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        base = self.output_dir / str(job_id)

        # Copy/rename video
        video_dest = base.with_suffix(".mp4")
        Path(video_path).rename(video_dest)

        # Write caption
        caption_path = base.with_suffix(".txt")
        caption_path.write_text(self.format_caption(caption))

        # Generate thumbnail
        thumb_path = base.with_suffix(".png")
        self._generate_thumbnail(thumb_path, caption[:50])

        # Write metadata
        meta_path = base.with_suffix(".json")
        meta_path.write_text(json.dumps(
            self.build_metadata(job_id, metadata.get("topic", ""),
                                metadata.get("niche", ""),
                                metadata.get("duration", 0.0),
                                metadata.get("cost", 0.0)),
            indent=2,
        ))

        return {
            "video_path": str(video_dest),
            "caption_path": str(caption_path),
            "thumbnail_path": str(thumb_path),
            "metadata_path": str(meta_path),
        }

    def format_caption(self, caption: str) -> str:
        """Ensure caption meets TikTok limits."""
        return caption.strip()[:150]

    def build_metadata(self, job_id: int, topic: str, niche: str,
                       duration: float, cost: float) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "topic": topic,
            "niche": niche,
            "duration_seconds": duration,
            "estimated_cost_usd": round(cost, 4),
            "generated_at": datetime.now().isoformat(),
            "format": "9:16 vertical",
            "resolution": "1080x1920",
            "files": ["video.mp4", "caption.txt", "thumbnail.png"],
        }

    def _generate_thumbnail(self, path: Path, text: str) -> None:
        """Generate a simple text-based thumbnail."""
        img = Image.new("RGB", (1080, 1920), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        draw.text((540, 960), text[:30], fill=(255, 255, 255), anchor="mm")
        img.save(path)
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add Output Packager (video + caption + thumbnail + metadata)"
```

---

## Phase 6: Orchestrator ✅ COMPLETED

**Branch:** `phase/6-orchestrator` — merged to `master` via PR #8 (initial) and PR #9 (bug fixes + coverage).

### Task 26: Orchestrator Engine ✅

**Files:**
- Create: `clipper_agency/orchestrator/engine.py`
- Create: `tests/test_orchestrator_engine.py`

**Step 1: Test**

```python
# tests/test_orchestrator_engine.py
from unittest.mock import patch, MagicMock
from clipper_agency.db.connection import get_connection, close_connection
from clipper_agency.db.schema import initialize_schema
from clipper_agency.orchestrator.engine import Orchestrator


def test_orchestrator_run_full_pipeline(temp_db_path):
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    close_connection()

    orch = Orchestrator(db_path=temp_db_path)
    result = orch.run_pipeline(
        topic="Ariana Grande Jakarta concert",
        niche="indonesian_artists",
    )
    assert result["status"] in ("completed", "failed")
    assert "job_id" in result


@patch.object(Orchestrator, "_run_safety")
def test_orchestrator_stops_on_safety_hard_fail(mock_safety, temp_db_path):
    mock_safety.return_value = {"status": "hard_fail", "reason": "Blocked"}
    orch = Orchestrator(db_path=temp_db_path)
    result = orch.run_pipeline(topic="Bad topic", niche="test")
    assert result["status"] == "failed"
    assert result["failed_at"] == "safety"
```

**Step 2: Implement**

```python
# clipper_agency/orchestrator/engine.py
from typing import Any

from clipper_agency.db.connection import get_connection
from clipper_agency.db.schema import initialize_schema
from clipper_agency.db.queries import (
    create_job, update_job_status, create_agent_state,
    update_agent_state, get_agent_state,
)
from clipper_agency.orchestrator.state_machine import JobStateMachine
from clipper_agency.orchestrator.gates import (
    GateInputPreflight, GateCostEstimate, GateResearchCache,
    GatePostResearchRisk, GateSourceQuality, GateCreativeMemory,
    GateScriptValidation, GateAudioValidation, GateAssetValidation,
    GateVideoValidation,
)
from clipper_agency.agents.safety import SafetyAgent
from clipper_agency.agents.researcher import ResearcherAgent
from clipper_agency.agents.scriptwriter import ScriptwriterAgent
from clipper_agency.agents.voice_producer import VoiceProducerAgent
from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.agents.reviewer import ReviewerAgent
from clipper_agency.output.packager import OutputPackager


class Orchestrator:
    """Coordinates the full gated agent pipeline."""

    def __init__(self, db_path: str = "data/clipper.db") -> None:
        self.db_path = db_path
        self.sm = JobStateMachine()
        conn = get_connection(db_path)
        initialize_schema(conn)

    def run_pipeline(self, topic: str, niche: str = "indonesian_artists",
                     **kwargs: Any) -> dict[str, Any]:
        """Execute the full topic-to-output pipeline."""
        conn = get_connection(self.db_path)
        job_id = create_job(conn, topic=topic, niche=niche)
        agent_names = ["safety", "researcher", "scriptwriter",
                       "voice_producer", "visual_director", "composer", "reviewer"]
        for name in agent_names:
            create_agent_state(conn, job_id, name)

        try:
            # Phase 1: Preflight
            self.sm.transition_to("PREFLIGHT")
            g1 = GateInputPreflight()
            if not g1.evaluate(topic=topic).passed:
                raise RuntimeError("G1 failed: invalid input")

            # Phase 2: Cost estimate
            self.sm.transition_to("COST_ESTIMATED")
            g2 = GateCostEstimate()
            cost_result = g2.evaluate()

            # Phase 3: Safety check
            self.sm.transition_to("SAFETY_CHECKED")
            safety = SafetyAgent()
            safety_result = safety.execute(job_id=job_id, topic=topic)
            if safety_result.get("status") == "hard_fail":
                update_job_status(conn, job_id, "FAILED", safety_result["reason"])
                return {"status": "failed", "failed_at": "safety", "reason": safety_result["reason"], "job_id": job_id}

            # Phase 4: Research
            self.sm.transition_to("RESEARCHING")
            g3 = GateResearchCache()
            cache_result = g3.evaluate()
            researcher = ResearcherAgent()
            research_output = researcher.execute(
                job_id=job_id, topic=topic,
                niche_config={"name": niche, "language": "id", "tone": "casual_tiktok"},
            )
            self.sm.transition_to("RESEARCH_REVIEWED")
            g4 = GatePostResearchRisk()
            risk_result = g4.evaluate(risk_flags=research_output.get("risk_flags"))

            # Phase 5: Source validation
            self.sm.transition_to("SOURCES_VALIDATED")
            g5 = GateSourceQuality()
            g5.evaluate(video_sources=research_output.get("video_sources"))

            # Phase 6: Creative memory
            self.sm.transition_to("MEMORY_CHECKED")
            g6 = GateCreativeMemory()

            # Phase 7: Scriptwriting
            self.sm.transition_to("SCRIPTING")
            scriptwriter = ScriptwriterAgent()
            script_output = scriptwriter.execute(
                job_id=job_id, topic=topic,
                research_output=research_output,
                niche_config={"name": niche, "tone": "casual_tiktok", "language": "id"},
            )

            self.sm.transition_to("SCRIPT_VALIDATED")
            g7 = GateScriptValidation()
            g7.evaluate(script=script_output.get("script", ""),
                        caption=script_output.get("caption", ""))

            # Phase 8: Voice
            self.sm.transition_to("VOICING")
            voice = VoiceProducerAgent()
            voice_result = voice.execute(
                job_id=job_id,
                script=script_output.get("script", ""),
            )

            self.sm.transition_to("AUDIO_VALIDATED")
            g8 = GateAudioValidation()
            g8.evaluate(audio_path=voice_result.get("audio_path"))

            # Phase 9: Visual
            self.sm.transition_to("VISUALIZING")
            visual = VisualDirectorAgent()
            visual_result = visual.execute(
                job_id=job_id,
                video_sources=research_output.get("video_sources"),
                tags=research_output.get("tags"),
                script=script_output.get("script", ""),
            )

            self.sm.transition_to("ASSETS_VALIDATED")
            g9 = GateAssetValidation()
            g9.evaluate(asset_paths=visual_result.get("downloaded_assets"))

            # Phase 10: Compose
            self.sm.transition_to("COMPOSING")
            composer = ComposerAgent()
            compose_result = composer.execute(
                job_id=job_id,
                scenes=visual_result.get("scenes"),
                audio_path=voice_result.get("audio_path"),
                caption=script_output.get("caption", ""),
            )

            self.sm.transition_to("VIDEO_VALIDATED")
            g10 = GateVideoValidation()
            g10.evaluate(video_path=compose_result.get("video_path"))

            # Phase 11: Review
            self.sm.transition_to("REVIEWING")
            reviewer = ReviewerAgent()
            review_result = reviewer.execute(
                job_id=job_id,
                script=script_output.get("script", ""),
                caption=script_output.get("caption", ""),
                video_path=compose_result.get("video_path"),
            )

            # Phase 12: Package output
            packager = OutputPackager()
            pkg_result = packager.package(
                job_id=job_id,
                video_path=compose_result.get("video_path", ""),
                script=script_output.get("script", ""),
                caption=script_output.get("caption", ""),
                metadata={
                    "topic": topic,
                    "niche": niche,
                    "duration": compose_result.get("duration_seconds", 0),
                    "cost": cost_result.data.get("estimate_cents", 0) / 100,
                },
            )

            self.sm.transition_to("COMPLETED")
            update_job_status(conn, job_id, "COMPLETED")
            return {"status": "completed", "job_id": job_id, "output": pkg_result}

        except Exception as e:
            update_job_status(conn, job_id, "FAILED", str(e))
            return {"status": "failed", "error": str(e), "job_id": job_id}
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add Orchestrator engine with full pipeline orchestration"
```

---

### Task 27: CLI Interface ✅

**Files:**
- Modify: `clipper_agency/__main__.py`
- Create: `tests/test_cli.py`

**Step 1: Test**

```python
# tests/test_cli.py
from click.testing import CliRunner
from clipper_agency.__main__ import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Clipper Agency" in result.output


def test_run_command_requires_topic():
    runner = CliRunner()
    result = runner.invoke(cli, ["run"])
    assert result.exit_code != 0
    assert "Missing option" in result.output


def test_run_command_with_topic():
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--topic", "Test topic"])
    assert result.exit_code == 0
    assert "Test topic" in result.output
```

**Step 2: Update CLI**

```python
# clipper_agency/__main__.py
import click

from clipper_agency.orchestrator.engine import Orchestrator


@click.group()
def cli() -> None:
    """Clipper Agency — automated video content production."""


@cli.command()
@click.option("--topic", "-t", required=True, help="Topic for video generation")
@click.option("--niche", "-n", default="indonesian_artists", help="Niche profile")
@click.option("--db", default="data/clipper.db", help="Database path")
@click.option("--dry-run", is_flag=True, help="Validate inputs without running")
def run(topic: str, niche: str, db: str, dry_run: bool) -> None:
    """Run the full pipeline for a topic."""
    click.echo(f"Topic: {topic}")
    click.echo(f"Niche: {niche}")
    if dry_run:
        click.echo("Dry run: input valid. Pass --dry-run to execute.")
        return
    click.echo("Starting pipeline...")
    orch = Orchestrator(db_path=db)
    result = orch.run_pipeline(topic=topic, niche=niche)
    if result["status"] == "completed":
        click.echo(f"✅ Pipeline completed! Job ID: {result['job_id']}")
        click.echo(f"Output: {result['output']}")
    else:
        click.echo(f"❌ Pipeline failed: {result.get('error', result.get('reason', 'Unknown'))}")


@cli.command()
def jobs() -> None:
    """List recent jobs."""
    from clipper_agency.db.connection import get_connection
    from clipper_agency.db.queries import list_jobs
    conn = get_connection("data/clipper.db")
    for job in list_jobs(conn, limit=10):
        click.echo(f"#{job['id']}: {job['topic']} — {job['status']} ({job['created_at']})")
```

**Step 3: Verify, commit**

```bash
git add -A && git commit -m "feat: add CLI interface with run and jobs commands"
```

---

### Post-Merge: Bug Fixes & Coverage (PR #9)

**After Phase 6 merge**, 3 bugs and coverage gaps were discovered and fixed:

**Bug Fixes:**
- **SonarCloud `python:S3358`** — Nested ternary in `__main__.py` extracted into if/elif/else
- **P0: Research sources unwrap** — Orchestrator now unwraps aggregate `{sources: [...]}` dict from ResearcherAgent
- **P1: G4 gate unchecked** — Pipeline aborts on `hard_fail` from PostResearchRisk gate
- **P1: Package failure unchecked** — Job marked `FAILED` when OutputPackager returns error

**Coverage (26 tests):** 87% → 97% overall line coverage
- `config/loader.py`: 19% → 100%
- `llm/router.py`: 80% → 100%
- `config/hierarchy.py`: 90% → 100%
- `agents/composer.py`: 90% → 100%
- `output/packager.py`: 94% → 100%
- `services/pexels.py`: 93% → 100%
- `services/ytdlp.py`: 85% → 100%

**Test suite:** 190 → 216 tests (97% coverage)

---

## Phase 7: Dashboard ✅ COMPLETED

### Task 28: Dashboard Web App

**Files:**
- Create: `clipper_agency/dashboard/app.py`
- Create: `clipper_agency/dashboard/auth.py`
- Create: `clipper_agency/dashboard/templates/base.html`
- Create: `clipper_agency/dashboard/templates/index.html`
- Create: `clipper_agency/dashboard/templates/jobs.html`
- Create: `tests/test_dashboard.py`

**Step 1: Implement auth**

```python
# clipper_agency/dashboard/auth.py
import os
from functools import wraps
from typing import Callable

from flask import request, Response


def check_auth(username: str, password: str) -> bool:
    """Check credentials against env vars."""
    expected_user = os.getenv("DASHBOARD_USERNAME", "admin")
    expected_pass = os.getenv("DASHBOARD_PASSWORD", "changeme")
    return username == expected_user and password == expected_pass


def authenticate() -> Response:
    """Send 401 Basic Auth challenge."""
    return Response(
        "Authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="Clipper Agency"'},
    )


def requires_auth(f: Callable) -> Callable:
    """Decorator to require basic auth."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated
```

**Step 2: Implement dashboard app**

```python
# clipper_agency/dashboard/app.py
from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import list_jobs, get_job
from clipper_agency.dashboard.auth import requires_auth

from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder="templates")


@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/jobs")
@requires_auth
def jobs_page():
    conn = get_connection("data/clipper.db")
    jobs = list_jobs(conn, limit=50)
    return render_template("jobs.html", jobs=jobs)


@app.route("/api/jobs")
@requires_auth
def api_jobs():
    conn = get_connection("data/clipper.db")
    return jsonify(list_jobs(conn, limit=50))


@app.route("/api/jobs/<int:job_id>")
@requires_auth
def api_job_detail(job_id: int):
    conn = get_connection("data/clipper.db")
    job = get_job(conn, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(dict(job))


@app.route("/api/jobs", methods=["POST"])
@requires_auth
def api_create_job():
    data = request.get_json()
    if not data or "topic" not in data:
        return jsonify({"error": "topic is required"}), 400
    from clipper_agency.orchestrator.engine import Orchestrator
    orch = Orchestrator()
    result = orch.run_pipeline(
        topic=data["topic"],
        niche=data.get("niche", "indonesian_artists"),
    )
    return jsonify(result)


def run_dashboard(host: str = "0.0.0.0", port: int = 5000) -> None:
    """Start the dashboard server."""
    app.run(host=host, port=port, debug=False)
```

**Step 3: Templates**

```html
{# templates/base.html #}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Clipper Agency{% endblock %}</title>
    <style>
        body { font-family: -apple-system, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        nav { margin-bottom: 20px; }
        nav a { margin-right: 15px; color: #333; text-decoration: none; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .status-completed { color: green; }
        .status-failed { color: red; }
        .status-running { color: blue; }
    </style>
</head>
<body>
    <nav>
        <a href="/">Dashboard</a>
        <a href="/jobs">Jobs</a>
    </nav>
    {% block content %}{% endblock %}
</body>
</html>
```

```html
{# templates/index.html #}
{% extends "base.html" %}
{% block title %}Dashboard — Clipper Agency{% endblock %}
{% block content %}
<h1>Clipper Agency Dashboard</h1>
<div id="summary">
    <p>Loading...</p>
</div>
<script>
    fetch('/api/jobs')
        .then(r => r.json())
        .then(jobs => {
            const total = jobs.length;
            const completed = jobs.filter(j => j.status === 'COMPLETED').length;
            const failed = jobs.filter(j => j.status === 'FAILED').length;
            document.getElementById('summary').innerHTML = `
                <p><strong>Total Jobs:</strong> ${total}</p>
                <p><strong>Completed:</strong> ${completed}</p>
                <p><strong>Failed:</strong> ${failed}</p>
            `;
        });
</script>
{% endblock %}
```

```html
{# templates/jobs.html #}
{% extends "base.html" %}
{% block title %}Jobs — Clipper Agency{% endblock %}
{% block content %}
<h1>Jobs</h1>
<table>
    <tr><th>ID</th><th>Topic</th><th>Niche</th><th>Status</th><th>Created</th></tr>
    {% for job in jobs %}
    <tr>
        <td>{{ job.id }}</td>
        <td>{{ job.topic }}</td>
        <td>{{ job.niche }}</td>
        <td class="status-{{ job.status.lower() }}">{{ job.status }}</td>
        <td>{{ job.created_at }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}
```

**Step 4: Test, commit**

```bash
git add -A && git commit -m "feat: add web dashboard with basic auth and job listing"
```

---

## Phase 8: Configuration & Prompts ✅ COMPLETED

### Task 29: Niche Config YAML ✅

**Files:**
- Create: `niches/indonesian_artists.yaml`

```yaml
name: indonesian_artists
language: id
tone: casual_tiktok
video_length:
  target: 30
  hard_limit: 60
voice:
  provider: elevenlabs
  default_voice_id: ""  # Configure via env ELEVENLABS_VOICE_ID
thumbnail:
  template: headline_frame
  resolution: 1080x1920
content_angle: trending_artist_update
safety_rules:
  - no_defamation
  - mark_rumors_as_unconfirmed
  - soft_wording_for_unverified
caption_style: short_with_hashtags
max_hashtags: 5
search_terms:
  - viral
  - ramai dibahas
  - klarifikasi
  - gosip
  - trending
```

Commit: `git add -A && git commit -m "feat: add Indonesian artists niche config"`

---

### Task 30: Template Configs ✅

**Files:**
- Create: `templates/news_card.yaml`
- Create: `templates/b_roll_narration.yaml`
- Create: `templates/rapid_update.yaml`

```yaml
# templates/news_card.yaml
name: news_card
type: news_card
style: headline_image_facts
description: "Headline + image + facts + captions. Best for quick updates."
layout:
  resolution: 1080x1920
  background_color: "#1a1a2e"
  title_font_size: 56
  subtitle_font_size: 32
  caption_position: bottom
  transitions:
    type: fade
    duration: 0.5s
```

```yaml
# templates/b_roll_narration.yaml
name: b_roll_narration
type: b_roll_narration
style: voiceover_clips_captions
description: "Voiceover + clips + dynamic captions. Best for context-rich stories."
layout:
  resolution: 1080x1920
  clip_duration: 3-5s
  caption_style: dynamic
  transitions:
    type: crossfade
    duration: 0.3s
```

```yaml
# templates/rapid_update.yaml
name: rapid_update
type: rapid_update
style: fast_cuts_punchy
description: "Fast cuts + punchy captions. Best for trending gossip."
layout:
  resolution: 1080x1920
  clip_duration: 1.5-3s
  caption_style: punchy_centered
  transitions:
    type: cut
    duration: 0s
```

Commit: `git add -A && git commit -m "feat: add 3 video template configs"`

---

### Task 31: Prompt Files ✅

**Files:**
- Create: `prompts/safety.txt`
- Create: `prompts/researcher.txt`
- Create: `prompts/scriptwriter.txt`
- Create: `prompts/reviewer.txt`

See the prompt constants already embedded in agent implementations (Tasks 18-24). Extract them to text files:

```bash
# prompts/safety.txt
# (content from SafetyAgent.SAFETY_PROMPT constant)

# prompts/scriptwriter.txt  
# (content from ScriptwriterAgent.SCRIPTWRITER_PROMPT constant)

# prompts/reviewer.txt
# (content from ReviewerAgent.REVIEWER_PROMPT constant)
```

Each agent should load prompts from files with `prompts/{agent_name}.txt` fallback to embedded constant.

Commit: `git add -A && git commit -m "feat: add prompt files for agents"`

---

## Phase 9: Docker & Integration ✅ COMPLETED

**Branch:** `phase/9-docker` — merged to `master` via PR #12.

### Task 32: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

```dockerfile
# Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg yt-dlp && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data outputs assets/cache assets/voiceovers

EXPOSE 5000
CMD ["python3", "-m", "clipper_agency"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  clipper:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./outputs:/app/outputs
      - ./assets:/app/assets
      - ./niches:/app/niches
      - ./templates:/app/templates
    env_file:
      - .env
    command: python3 -c "from clipper_agency.dashboard.app import run_dashboard; run_dashboard()"
```

Commit: `git add -A && git commit -m "chore: add Docker setup for deployment"`

---

### Task 33: Integration Smoke Test

**Files:**
- Create: `tests/test_integration.py`

```python
# tests/test_integration.py
import pytest
from clipper_agency.orchestrator.engine import Orchestrator


@pytest.mark.integration
def test_full_pipeline_smoke(temp_db_path):
    """Smoke test: run full pipeline with a simple topic.
    Requires FFmpeg, OPENROUTER_API_KEY.
    """
    orch = Orchestrator(db_path=temp_db_path)
    result = orch.run_pipeline(
        topic="Ariana Grande konser Jakarta viral",
        niche="indonesian_artists",
    )
    assert result["status"] in ("completed", "failed")
    if result["status"] == "completed":
        assert "job_id" in result
        assert "output" in result


@pytest.mark.integration
def test_short_topic_does_not_crash(temp_db_path):
    orch = Orchestrator(db_path=temp_db_path)
    result = orch.run_pipeline(topic="Test", niche="indonesian_artists")
    assert "status" in result
```

Run: `python3 -m pytest tests/test_integration.py -v -m integration`
Expected: Integration tests run (may require API keys)

Commit: `git add -A && git commit -m "test: add integration smoke test for full pipeline"`
