from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisResult:
    route_id: str
    scores: dict[str, float] = field(default_factory=dict)
    recommendation: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
