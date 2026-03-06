"""Tests for PII guardrail / privacy module."""

import json
import pytest
from claude_analytics.privacy import (
    is_private_project,
    ProjectRedactor,
    DEFAULT_PRIVATE_PATTERNS,
)


class TestIsPrivateProject:
    def test_stock_project(self):
        assert is_private_project("StockTracker", config={}) is True

    def test_portfolio_project(self):
        assert is_private_project("my-portfolio-app", config={}) is True

    def test_financial_project(self):
        assert is_private_project("FinancialAssistant", config={}) is True

    def test_broker_project(self):
        assert is_private_project("TigerBrokerTools", config={}) is True

    def test_market_monitor(self):
        assert is_private_project("MarketMonitoring", config={}) is True

    def test_safe_project(self):
        assert is_private_project("MewtwoAI", config={}) is False

    def test_safe_generic_project(self):
        assert is_private_project("my-website", config={}) is False

    def test_case_insensitive(self):
        assert is_private_project("STOCK-tracker", config={}) is True

    def test_explicit_private_project(self):
        config = {"private_projects": ["SecretApp"]}
        assert is_private_project("SecretApp", config=config) is True

    def test_explicit_does_not_match_other(self):
        config = {"private_projects": ["SecretApp"]}
        assert is_private_project("PublicApp", config=config) is False

    def test_custom_pattern(self):
        config = {"private_patterns": [r"\bfoobar\b"]}
        assert is_private_project("my-foobar-project", config=config) is True

    def test_show_all_disables_detection(self):
        config = {"show_all": True}
        assert is_private_project("StockTracker", config=config) is False

    def test_health_project(self):
        assert is_private_project("HealthInsurance", config={}) is True

    def test_password_project(self):
        assert is_private_project("password-manager", config={}) is True

    def test_crypto_project(self):
        assert is_private_project("CryptoWallet", config={}) is True

    def test_cpng_project(self):
        assert is_private_project("CPNG-analysis", config={}) is True

    def test_ai_coding_observability_is_safe(self):
        assert is_private_project("AI-Coding-Observability", config={}) is False


class TestProjectRedactor:
    def test_safe_project_unchanged(self):
        r = ProjectRedactor(config={})
        assert r.redact("MewtwoAI") == "MewtwoAI"

    def test_sensitive_project_redacted(self):
        r = ProjectRedactor(config={})
        result = r.redact("FinancialAssistant")
        assert result.startswith("Private-")
        assert "Financial" not in result

    def test_consistent_mapping(self):
        r = ProjectRedactor(config={})
        first = r.redact("StockTracker")
        second = r.redact("StockTracker")
        assert first == second

    def test_different_projects_different_labels(self):
        r = ProjectRedactor(config={})
        a = r.redact("StockTracker")
        b = r.redact("PortfolioManager")
        assert a != b
        assert a == "Private-1"
        assert b == "Private-2"

    def test_show_all_returns_original(self):
        r = ProjectRedactor(config={"show_all": True})
        assert r.redact("StockTracker") == "StockTracker"

    def test_redact_dict(self):
        r = ProjectRedactor(config={})
        data = {
            "MewtwoAI": {"coding": 100},
            "FinancialAssistant": {"data": 200},
        }
        result = r.redact_dict(data)
        assert "MewtwoAI" in result
        assert "FinancialAssistant" not in result
        assert any(k.startswith("Private-") for k in result)
        # Values preserved
        private_key = [k for k in result if k.startswith("Private-")][0]
        assert result[private_key] == {"data": 200}

    def test_redact_dict_empty(self):
        r = ProjectRedactor(config={})
        assert r.redact_dict({}) == {}

    def test_show_all_property(self):
        assert ProjectRedactor(config={}).show_all is False
        assert ProjectRedactor(config={"show_all": True}).show_all is True

    def test_loads_config_from_file(self, tmp_path):
        """Config file is loaded when no explicit config is passed."""
        config_path = tmp_path / "privacy.json"
        config_path.write_text(json.dumps({"private_projects": ["CustomApp"]}))

        from unittest.mock import patch
        with patch("claude_analytics.privacy.CONFIG_PATH", config_path):
            r = ProjectRedactor()
            assert r.redact("CustomApp").startswith("Private-")
            assert r.redact("SafeApp") == "SafeApp"

    def test_missing_config_file_uses_defaults(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        from unittest.mock import patch
        with patch("claude_analytics.privacy.CONFIG_PATH", config_path):
            r = ProjectRedactor()
            # Defaults still catch financial projects
            assert r.redact("StockTracker").startswith("Private-")


class TestDefaultPatterns:
    def test_patterns_are_valid_regex(self):
        import re
        for pattern in DEFAULT_PRIVATE_PATTERNS:
            re.compile(pattern, re.IGNORECASE)  # should not raise

    def test_at_least_5_patterns(self):
        assert len(DEFAULT_PRIVATE_PATTERNS) >= 5
