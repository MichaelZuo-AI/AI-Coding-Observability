"""Tests for SQLite classification cache."""

import pytest
from pathlib import Path
from claude_analytics.cache import get_cached, set_cached, cache_stats, _hash_content


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_cache.db"


class TestCache:
    def test_miss_returns_none(self, tmp_db):
        assert get_cached("hello", [], db_path=tmp_db) is None

    def test_set_and_get(self, tmp_db):
        set_cached("fix the bug", ["Bash"], "debug", db_path=tmp_db)
        assert get_cached("fix the bug", ["Bash"], db_path=tmp_db) == "debug"

    def test_different_content_different_hash(self, tmp_db):
        set_cached("fix the bug", [], "debug", db_path=tmp_db)
        assert get_cached("add a feature", [], db_path=tmp_db) is None

    def test_tool_order_independent(self, tmp_db):
        set_cached("test", ["Edit", "Write"], "coding", db_path=tmp_db)
        # Same tools in different order should match (sorted internally)
        assert get_cached("test", ["Write", "Edit"], db_path=tmp_db) == "coding"

    def test_overwrite(self, tmp_db):
        set_cached("ambiguous msg", [], "chat", db_path=tmp_db)
        set_cached("ambiguous msg", [], "coding", db_path=tmp_db)
        assert get_cached("ambiguous msg", [], db_path=tmp_db) == "coding"

    def test_cache_stats(self, tmp_db):
        set_cached("msg1", [], "debug", db_path=tmp_db)
        set_cached("msg2", [], "debug", db_path=tmp_db)
        set_cached("msg3", [], "coding", db_path=tmp_db)
        stats = cache_stats(db_path=tmp_db)
        assert stats == {"debug": 2, "coding": 1}

    def test_cache_stats_empty(self, tmp_path):
        db = tmp_path / "nonexistent.db"
        assert cache_stats(db_path=db) == {}

    def test_hash_deterministic(self):
        h1 = _hash_content("hello", ["Edit"])
        h2 = _hash_content("hello", ["Edit"])
        assert h1 == h2

    def test_hash_different_for_different_input(self):
        h1 = _hash_content("hello", [])
        h2 = _hash_content("world", [])
        assert h1 != h2
