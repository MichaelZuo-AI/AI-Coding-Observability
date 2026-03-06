"""Phase 4a: Output metrics + simple input metrics for engineering efficiency."""

from __future__ import annotations

from dataclasses import dataclass
from .models import ActivityBlock

CORE_CATEGORIES = {"coding", "design", "debug"}
OVERHEAD_CATEGORIES = {"chat", "devops"}


@dataclass
class EfficiencyMetrics:
    # Output metrics
    focus_ratio: float = 0.0
    efficiency_score: float = 0.0  # task_resolution × focus_ratio (partial until quality.py)

    # Input metrics
    debug_tax: float = 0.0
    interaction_density: float = 0.0
    chat_devops_overhead: float = 0.0

    # Lifecycle stage durations (seconds)
    design_seconds: int = 0
    testing_seconds: int = 0
    deployment_seconds: int = 0
    coding_seconds: int = 0


def compute_efficiency(
    blocks: list[ActivityBlock],
    message_count: int,
    active_hours: float,
    task_resolution_efficiency: float | None = None,
) -> EfficiencyMetrics:
    """Compute efficiency metrics from activity blocks.

    Args:
        blocks: classified activity blocks for a single project
        message_count: total user messages in the project
        active_hours: total active hours for the project
        task_resolution_efficiency: if provided (from quality.py), used for full unified score
    """
    if not blocks:
        return EfficiencyMetrics()

    cat_seconds: dict[str, int] = {}
    for block in blocks:
        cat_seconds[block.category] = cat_seconds.get(block.category, 0) + block.duration_seconds

    total_seconds = sum(cat_seconds.values())
    coding_secs = cat_seconds.get("coding", 0)
    debug_secs = cat_seconds.get("debug", 0)
    design_secs = cat_seconds.get("design", 0)
    devops_secs = cat_seconds.get("devops", 0)
    chat_secs = cat_seconds.get("chat", 0)

    # Testing: blocks classified as "review" touching test files would be ideal,
    # but we don't have file info in blocks. Use 0 for now (testing duration
    # requires Phase 4b rework detection to identify test-file commits).
    testing_secs = 0

    # Focus ratio
    core_seconds = sum(cat_seconds.get(c, 0) for c in CORE_CATEGORIES)
    focus_ratio = core_seconds / total_seconds if total_seconds > 0 else 0.0

    # Debug tax
    debug_tax = debug_secs / coding_secs if coding_secs > 0 else 0.0

    # Interaction density
    interaction_density = message_count / active_hours if active_hours > 0 else 0.0

    # Chat & devops overhead
    overhead_secs = chat_secs + devops_secs
    chat_devops_overhead = overhead_secs / total_seconds if total_seconds > 0 else 0.0

    # Unified score (partial: use 1.0 for task_resolution if not provided)
    tre = task_resolution_efficiency if task_resolution_efficiency is not None else 1.0
    efficiency_score = tre * focus_ratio

    return EfficiencyMetrics(
        focus_ratio=focus_ratio,
        efficiency_score=efficiency_score,
        debug_tax=debug_tax,
        interaction_density=interaction_density,
        chat_devops_overhead=chat_devops_overhead,
        design_seconds=design_secs,
        testing_seconds=testing_secs,
        deployment_seconds=devops_secs,
        coding_seconds=coding_secs,
    )
