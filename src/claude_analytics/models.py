from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime
    tool_uses: list[str] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    project: str
    messages: list[Message] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    active_seconds: int = 0


@dataclass
class ActivityBlock:
    category: str  # "coding" | "debug" | "design" | "review" | "devops" | "data" | "chat" | "other"
    start_time: datetime
    duration_seconds: int
    message_count: int
    tool_uses: list[str] = field(default_factory=list)
    project: str = ""


@dataclass
class OrchestrationSession:
    session_id: str
    project: str
    total_duration: int  # wall-clock seconds
    intent_length: int  # chars in initial prompt
    steering_count: int
    precision_score: float  # 1 / (1 + steering_count)
    tier: str  # "flawless" | "clean" | "guided" | "heavy"
    has_outcome: bool  # did session produce commits?
    phase_sequence: list[str] = field(default_factory=list)
    message_count: int = 0
    time_to_first_commit: int | None = None
