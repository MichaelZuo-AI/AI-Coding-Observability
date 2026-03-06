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

    # ------------------------------------------------------------------
    # Additional edge cases
    # ------------------------------------------------------------------

    def test_hash_length_is_32_chars(self):
        h = _hash_content("some content", ["Edit"])
        assert len(h) == 32

    def test_hash_differs_for_same_content_different_tools(self):
        h1 = _hash_content("hello", [])
        h2 = _hash_content("hello", ["Edit"])
        assert h1 != h2

    def test_set_cached_with_custom_model(self, tmp_db):
        """model parameter is stored and does not affect retrieval by content hash."""
        set_cached("content", [], "coding", model="gpt-4", db_path=tmp_db)
        assert get_cached("content", [], db_path=tmp_db) == "coding"

    def test_multiple_distinct_entries_in_same_db(self, tmp_db):
        set_cached("msg1", [], "coding", db_path=tmp_db)
        set_cached("msg2", ["Bash"], "debug", db_path=tmp_db)
        set_cached("msg3", ["Edit"], "devops", db_path=tmp_db)
        assert get_cached("msg1", [], db_path=tmp_db) == "coding"
        assert get_cached("msg2", ["Bash"], db_path=tmp_db) == "debug"
        assert get_cached("msg3", ["Edit"], db_path=tmp_db) == "devops"

    def test_get_cached_returns_none_for_wrong_tools(self, tmp_db):
        """Same content but different tools should be a cache miss."""
        set_cached("hello", ["Edit"], "coding", db_path=tmp_db)
        assert get_cached("hello", ["Write"], db_path=tmp_db) is None

    def test_get_cached_on_empty_existing_db(self, tmp_db):
        """DB that exists but has no rows should return None, not raise."""
        # Create the table by doing one set/get round-trip, then we test empty
        # Actually just call get on fresh db (table gets created on first connection)
        result = get_cached("no entry here", [], db_path=tmp_db)
        assert result is None

    def test_cache_stats_multiple_categories(self, tmp_db):
        set_cached("a", [], "coding", db_path=tmp_db)
        set_cached("b", [], "debug", db_path=tmp_db)
        set_cached("c", [], "design", db_path=tmp_db)
        set_cached("d", [], "coding", db_path=tmp_db)
        stats = cache_stats(db_path=tmp_db)
        assert stats["coding"] == 2
        assert stats["debug"] == 1
        assert stats["design"] == 1

    def test_overwrite_preserves_total_count(self, tmp_db):
        """Overwriting an entry should replace in-place, not add a second row."""
        set_cached("dupe", [], "chat", db_path=tmp_db)
        set_cached("dupe", [], "coding", db_path=tmp_db)
        stats = cache_stats(db_path=tmp_db)
        # Total entries should be exactly 1
        assert sum(stats.values()) == 1

    def test_many_tools_sorted_consistently(self, tmp_db):
        """Tool list order should not matter — same hash regardless of order."""
        tools_a = ["Bash", "Edit", "Read", "Write"]
        tools_b = ["Write", "Read", "Edit", "Bash"]
        set_cached("msg", tools_a, "coding", db_path=tmp_db)
        assert get_cached("msg", tools_b, db_path=tmp_db) == "coding"
