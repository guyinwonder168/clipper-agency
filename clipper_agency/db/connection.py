"""SQLite connection management with WAL mode and thread-safe singleton."""

import sqlite3
from pathlib import Path
from threading import Lock, RLock

_connections: dict[str, sqlite3.Connection] = {}
_conn_lock = Lock()
# Process-wide REENTRANT write lock serializing all DB writes on the shared
# singleton connection. SQLite legacy-mode transactions are connection-scoped,
# not thread-scoped, so with a shared check_same_thread=False connection a
# concurrent thread's conn.commit() would commit ANOTHER thread's half-open
# transaction. Every public committing helper in queries.py acquires this, and
# the G7 atomic-transaction path holds it across both writes + commit (PR #86,
# Codex P2 r3496171628). RLock so a code path that already holds it may call a
# public helper without deadlock.
_write_lock = RLock()


def db_write_lock() -> RLock:
    """Return the process-wide reentrant DB write lock.

    Used as ``with db_write_lock():`` around every committing write in
    ``queries.py`` and around the G7 hard-fail atomic transaction in the
    orchestrator engine. Guarantees no concurrent thread can interleave a
    ``conn.commit()`` into this thread's open transaction on the shared
    singleton connection.
    """
    return _write_lock


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
