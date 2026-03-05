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
    category: str  # "coding" | "debug" | "design" | "review" | "devops" | "other"
    start_time: datetime
    duration_seconds: int
    message_count: int
    tool_uses: list[str] = field(default_factory=list)
    project: str = ""
