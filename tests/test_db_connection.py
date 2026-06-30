"""Tests for database connection management."""

import sqlite3

from clipper_agency.db.connection import close_connection, db_write_lock, get_connection


def test_get_connection(temp_db_path):
    """Connection is a valid sqlite3.Connection."""
    conn = get_connection(temp_db_path)
    assert isinstance(conn, sqlite3.Connection)
    # WAL mode should be enabled
    cursor = conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"
    close_connection()


def test_get_connection_singleton(temp_db_path):
    """Same db_path returns the same connection object."""
    conn1 = get_connection(temp_db_path)
    conn2 = get_connection(temp_db_path)
    assert conn1 is conn2  # Same connection returned
    close_connection()


def test_advisory_lock(temp_db_path):
    """Basic query works — advisory lock is a no-op for SQLite."""
    conn = get_connection(temp_db_path)
    conn.execute("SELECT 1")
    close_connection()


def test_db_write_lock_is_reentrant(temp_db_path):
    """The DB write lock is reentrant (RLock) so a code path that already holds
    it may call a public committing helper (which also acquires it) without
    deadlock (PR #86, Codex P2 r3496171628)."""
    lock = db_write_lock()
    with lock:
        with lock:  # reentrant acquire must not block
            # A third non-blocking acquire from the SAME thread succeeds.
            assert lock.acquire(blocking=False) is True
            lock.release()
    close_connection()
