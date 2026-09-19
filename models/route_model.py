import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Tuple


# ============================================================
# Enum 정의
# ============================================================

class TransportMode(str, Enum):
    """이동 수단."""
    CAR      = "car"
    BUS      = "bus"
    BICYCLE  = "bicycle"
    WALKING  = "walk"
    COMBINED = "combined"

    def label(self) -> str:
        labels = {
            "car":      "자차",
            "bus":      "버스",
            "bicycle":  "자전거",
            "walk":     "도보",
            "combined": "대중교통+보행",
        }
        return labels[self.value]


class DayType(str, Enum):
    """요일 유형."""
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"

    def label(self) -> str:
        labels = {"weekday": "평일", "weekend": "주말", "holiday": "휴일"}
        return labels[self.value]


class WeatherCondition(str, Enum):
    """날씨 상태."""
    SUNNY  = "sunny"
    RAINY  = "rainy"
    SNOWY  = "snowy"
    CLOUDY = "cloudy"
    WINDY  = "windy"

    def label(self) -> str:
        labels = {
            "sunny":  "맑음",
            "rainy":  "비",
            "snowy":  "눈",
            "cloudy": "흐림",
            "windy":  "바람",
        }
        return labels[self.value]


# ============================================================
# RouteCondition dataclass
# ============================================================

_VALID_TRAFFIC = {"normal", "heavy", "light"}

@dataclass
class RouteCondition:
    """경로 탐색 조건."""
    transport_mode:    TransportMode
    departure_time:    datetime
    day_type:          DayType
    weather:           WeatherCondition
    traffic_condition: str  = "normal"   # "normal" | "heavy" | "light"
    prefer_safety:     bool = False
    avoid_toll:        bool = False

    # ── 유효성 검증 ─────────────────────────────────────────
    def validate(self) -> bool:
        """필수 값 및 허용 범위를 검증한다. 오류 시 ValueError."""
        errors: list[str] = []

        if not isinstance(self.transport_mode, TransportMode):
            errors.append(f"transport_mode가 TransportMode Enum이 아닙니다: {self.transport_mode}")
        if not isinstance(self.departure_time, datetime):
            errors.append(f"departure_time이 datetime이 아닙니다: {self.departure_time}")
        if not isinstance(self.day_type, DayType):
            errors.append(f"day_type이 DayType Enum이 아닙니다: {self.day_type}")
        if not isinstance(self.weather, WeatherCondition):
            errors.append(f"weather가 WeatherCondition Enum이 아닙니다: {self.weather}")
        if self.traffic_condition not in _VALID_TRAFFIC:
            errors.append(f"traffic_condition은 {_VALID_TRAFFIC} 중 하나여야 합니다: {self.traffic_condition}")

        if errors:
            raise ValueError("RouteCondition 유효성 오류:\n" + "\n".join(f"  - {e}" for e in errors))
        return True

    # ── 직렬화 ──────────────────────────────────────────────
    def to_dict(self) -> Dict:
        return {
            "transport_mode":    self.transport_mode.value,
            "departure_time":    self.departure_time.isoformat(),
            "day_type":          self.day_type.value,
            "weather":           self.weather.value,
            "traffic_condition": self.traffic_condition,
            "prefer_safety":     self.prefer_safety,
            "avoid_toll":        self.avoid_toll,
        }

    # ── 문자열 표현 ──────────────────────────────────────────
    def __str__(self) -> str:
        return (
            f"[이동수단: {self.transport_mode.value}] "
            f"[시간: {self.departure_time.strftime('%H:%M')}] "
            f"[요일: {self.day_type.label()}] "
            f"[날씨: {self.weather.label()}] "
            f"[교통: {self.traffic_condition}]"
            + (" [안전우선]" if self.prefer_safety else "")
            + (" [톨게이트회피]" if self.avoid_toll else "")
        )

    def __repr__(self) -> str:
        return (
            f"RouteCondition("
            f"mode={self.transport_mode.value!r}, "
            f"time={self.departure_time.strftime('%Y-%m-%d %H:%M')!r}, "
            f"day={self.day_type.value!r}, "
            f"weather={self.weather.value!r}, "
            f"traffic={self.traffic_condition!r})"
        )


# ============================================================
# RouteResult dataclass  (API 응답 정규화 결과)
# ============================================================

@dataclass
class RouteResult:
    """단일 API 제공자의 경로 탐색 결과."""
    provider:      str
    distance_m:    int
    duration_s:    int
    toll_fee:      int   = 0
    taxi_fee:      int   = 0
    transit_legs:  list  = field(default_factory=list)  # ODsay 대중교통 구간 정보
    raw:           dict  = field(default_factory=dict)

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000

    @property
    def duration_min(self) -> float:
        return self.duration_s / 60

    def to_dict(self) -> Dict:
        return {
            "provider":    self.provider,
            "distance_m":  self.distance_m,
            "distance_km": round(self.distance_km, 3),
            "duration_s":  self.duration_s,
            "duration_min": round(self.duration_min, 2),
            "toll_fee":    self.toll_fee,
            "taxi_fee":    self.taxi_fee,
        }

    def __str__(self) -> str:
        return (
            f"[{self.provider}] "
            f"{self.distance_km:.2f}km / "
            f"{self.duration_min:.1f}분 / "
            f"통행료 {self.toll_fee:,}원"
        )

    def __repr__(self) -> str:
        return (
            f"RouteResult(provider={self.provider!r}, "
            f"distance_km={self.distance_km:.2f}, "
            f"duration_min={self.duration_min:.1f})"
        )


# ============================================================
# Route dataclass  (출발지·목적지 + 조건 + 결과)
# ============================================================

@dataclass
class Route:
    """출발지·목적지 및 탐색 조건을 포함한 완전한 경로 정보."""
    start_address: str
    end_address:   str
    start_coords:  Tuple[float, float]   # (위도, 경도)
    end_coords:    Tuple[float, float]
    distance:      float                 # 단위: m
    condition:     RouteCondition
    created_at:    datetime = field(default_factory=datetime.now)
    results:       Dict[str, RouteResult] = field(default_factory=dict)
    metadata:      Dict = field(default_factory=dict)

    # ── 프로퍼티 ─────────────────────────────────────────────
    @property
    def distance_km(self) -> float:
        """거리(km) 반환."""
        return self.distance / 1000

    # ── 유효성 검증 ─────────────────────────────────────────
    def validate(self) -> bool:
        """좌표 범위 및 주소 입력 여부를 검증한다."""
        errors: list[str] = []

        if not self.start_address.strip():
            errors.append("start_address가 비어 있습니다.")
        if not self.end_address.strip():
            errors.append("end_address가 비어 있습니다.")

        for label, coords in [("start_coords", self.start_coords), ("end_coords", self.end_coords)]:
            lat, lon = coords
            if not (-90 <= lat <= 90):
                errors.append(f"{label} 위도 범위 오류: {lat}")
            if not (-180 <= lon <= 180):
                errors.append(f"{label} 경도 범위 오류: {lon}")

        if self.distance < 0:
            errors.append(f"distance는 0 이상이어야 합니다: {self.distance}")

        # 조건 검증도 함께 수행
        self.condition.validate()

        if errors:
            raise ValueError("Route 유효성 오류:\n" + "\n".join(f"  - {e}" for e in errors))
        return True

    # ── 직렬화 ──────────────────────────────────────────────
    def to_dict(self) -> Dict:
        return {
            "start_address": self.start_address,
            "end_address":   self.end_address,
            "start_coords":  list(self.start_coords),
            "end_coords":    list(self.end_coords),
            "distance_m":    self.distance,
            "distance_km":   round(self.distance_km, 3),
            "condition":     self.condition.to_dict(),
            "created_at":    self.created_at.isoformat(),
            "results":       {k: v.to_dict() for k, v in self.results.items()},
            "metadata":      self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    # ── 문자열 표현 ──────────────────────────────────────────
    def __str__(self) -> str:
        return f"{self.start_address} → {self.end_address} ({self.distance_km:.2f}km)"

    def __repr__(self) -> str:
        return (
            f"Route("
            f"start={self.start_address!r}, "
            f"end={self.end_address!r}, "
            f"distance_km={self.distance_km:.2f}, "
            f"mode={self.condition.transport_mode.value!r}, "
            f"created_at={self.created_at.strftime('%Y-%m-%d %H:%M')!r})"
        )
