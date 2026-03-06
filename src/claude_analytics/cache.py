"""SQLite cache for LLM-based classification results."""

import hashlib
import sqlite3
from pathlib import Path

CACHE_DIR = Path.home() / ".claude-analytics"
CACHE_DB = CACHE_DIR / "classification_cache.db"


def _get_connection(db_path: Path = CACHE_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS classifications (
            content_hash TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT 'claude-cli'
        )"""
    )
    conn.commit()
    return conn


def _hash_content(content: str, tool_uses: list[str]) -> str:
    key = content + "|" + ",".join(sorted(tool_uses))
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def get_cached(content: str, tool_uses: list[str], db_path: Path = CACHE_DB) -> str | None:
    """Look up a cached classification. Returns category or None."""
    content_hash = _hash_content(content, tool_uses)
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT category FROM classifications WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_cached(
    content: str,
    tool_uses: list[str],
    category: str,
    model: str = "claude-cli",
    db_path: Path = CACHE_DB,
) -> None:
    """Store a classification result in the cache."""
    content_hash = _hash_content(content, tool_uses)
    conn = _get_connection(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO classifications (content_hash, category, model) VALUES (?, ?, ?)",
            (content_hash, category, model),
        )
        conn.commit()
    finally:
        conn.close()


def cache_stats(db_path: Path = CACHE_DB) -> dict[str, int]:
    """Return counts of cached classifications by category."""
    if not db_path.exists():
        return {}
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT category, COUNT(*) FROM classifications GROUP BY category"
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()
