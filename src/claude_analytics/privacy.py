"""PII guardrail — automatically detects and redacts sensitive project names.

Projects matching financial/personal patterns are replaced with generic labels
like "Private-1", "Private-2" in all output (CLI report, dashboard, sessions).

Configurable via ~/.claude-analytics/privacy.json:
{
    "private_patterns": ["stock", "portfolio", ...],  // extra patterns
    "private_projects": ["MyBrokerApp"],               // exact project names
    "show_all": false                                   // set true to disable redaction
}
"""

import json
import re
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude-analytics" / "privacy.json"

# Default patterns that indicate personally sensitive projects.
# No \b word boundaries — these need to match inside camelCase/PascalCase names
# like "StockTracker", "FinancialAssistant", "MarketMonitoring".
DEFAULT_PRIVATE_PATTERNS: list[str] = [
    r"(stock|rsu|option|portfolio|wealth|brokerage|broker)",
    r"(finance|financial|accounting|tax|dividend|earning)",
    r"(bank|banking|savings?|retirement|401k|ira|pension)",
    r"(invest|trading|trader|crypto|bitcoin|wallet)",
    r"(salary|income|expense|budget|debt|mortgage|loan)",
    r"(medical|health|insurance|patient|prescription)",
    r"(password|credential|secret|token|auth-key)",
    r"(tiger|schwab|fidelity|vanguard|robinhood|etrade|coinbase)",
    r"(cpng|personal|private|confidential)",
    r"(market.?monitor|wealth.?track|money)",
]


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _build_patterns(config: dict) -> list[re.Pattern]:
    patterns = list(DEFAULT_PRIVATE_PATTERNS)
    patterns.extend(config.get("private_patterns", []))
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def is_private_project(project_name: str, config: dict | None = None) -> bool:
    """Check if a project name matches any private/sensitive pattern."""
    if config is None:
        config = _load_config()

    if config.get("show_all", False):
        return False

    # Exact matches from config
    explicit = config.get("private_projects", [])
    if project_name in explicit:
        return True

    # Pattern matching
    for pattern in _build_patterns(config):
        if pattern.search(project_name):
            return True

    return False


class ProjectRedactor:
    """Maps real project names to redacted labels, maintaining consistency.

    The same real name always maps to the same "Private-N" label within a session.
    """

    def __init__(self, config: dict | None = None):
        self._config = config if config is not None else _load_config()
        self._mapping: dict[str, str] = {}
        self._counter = 0

    @property
    def show_all(self) -> bool:
        return self._config.get("show_all", False)

    def redact(self, project_name: str) -> str:
        """Return the redacted name if private, or the original name if safe."""
        if self.show_all:
            return project_name

        if not is_private_project(project_name, self._config):
            return project_name

        if project_name not in self._mapping:
            self._counter += 1
            self._mapping[project_name] = f"Private-{self._counter}"

        return self._mapping[project_name]

    def redact_dict(self, data: dict) -> dict:
        """Redact project names in dict keys, returning a new dict."""
        return {self.redact(k): v for k, v in data.items()}
