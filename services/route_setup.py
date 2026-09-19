"""
경로 자동 설정 시스템.

RouteSetupEnhanced: 카카오맵 핸들러 기반으로 경로를 구성하고,
서울 주요 랜드마크에서 랜덤 경로를 자동 선택한다.
"""

import random
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from tabulate import tabulate

from core.kakao_api_handler import KakaoAPIHandler
from core.tmap_api_handler import TmapAPIHandler as TMapAPIHandler
from models.route_model import (
    DayType,
    Route,
    RouteCondition,
    RouteResult,
    TransportMode,
    WeatherCondition,
)
from utils.logger import get_logger

# ── 서울 주요 랜드마크 좌표 (위도, 경도) ────────────────────────────────────
LANDMARKS: Dict[str, Tuple[float, float]] = {
    "강남역":       (37.4979, 127.0276),
    "서울역":       (37.5525, 126.9723),
    "명동":         (37.5643, 126.9835),
    "홍대":         (37.5585, 126.9242),
    "잠실":         (37.5139, 127.1070),
    "동대문":       (37.5665, 127.0106),
    "인천공항":     (37.4502, 126.4407),
    "김포공항":     (37.6213, 126.8009),
    "신촌":         (37.5565, 126.9344),
    "강북":         (37.6312, 127.0030),
    "양재":         (37.4846, 127.0325),
    "태릉":         (37.6157, 127.0511),
    "상암":         (37.5771, 126.8850),
    "용산":         (37.5305, 126.9903),
    "청담":         (37.5267, 127.0514),
    "강북삼성병원": (37.6277, 127.0033),
    "아산병원":     (37.5927, 126.9956),
    "DDP":          (37.5647, 127.0099),
    "나인원핸드레드": (37.5248, 127.0278),
    "코엑스":       (37.5149, 127.0595),
}

# 이동 수단별 적정 거리 기준 (미터)
_MODE_DISTANCE: Dict[TransportMode, Tuple[Optional[float], Optional[float]]] = {
    TransportMode.WALKING:  (None,   5_000),
    TransportMode.BICYCLE:  (None,  50_000),
    TransportMode.BUS:      (1_000,  None),
    TransportMode.CAR:      (None,   None),
    TransportMode.COMBINED: (3_000,  None),
}

# 기본 RouteCondition
_DEFAULT_CONDITION = RouteCondition(
    transport_mode=TransportMode.CAR,
    departure_time=datetime.now().replace(hour=9, minute=0, second=0, microsecond=0),
    day_type=DayType.WEEKDAY,
    weather=WeatherCondition.SUNNY,
    traffic_condition="normal",
)


class RouteSetupEnhanced:
    """카카오맵 핸들러를 주입받아 경로를 구성하고 관리하는 클래스.

    Args:
        kakao_handler: 초기화된 KakaoAPIHandler 인스턴스

    Example:
        >>> from core.kakao_api_handler import KakaoAPIHandler
        >>> from config.api_config import config
        >>> handler = KakaoAPIHandler(config.kakao.api_key)
        >>> rse = RouteSetupEnhanced(handler)
        >>> routes = rse.auto_select_route(num_routes=3)
        >>> len(routes) <= 3
        True
    """

    def __init__(self, kakao_handler: KakaoAPIHandler) -> None:
        self.kakao:    KakaoAPIHandler         = kakao_handler
        self.routes:   List[Route]             = []
        self.landmarks: Dict[str, Tuple[float, float]] = LANDMARKS.copy()
        self._logger = get_logger(self.__class__.__name__)
        self._logger.info(
            "RouteSetupEnhanced 초기화 | 랜드마크 %d개", len(self.landmarks)
        )

    # =========================================================
    # 1. 경로 설정
    # =========================================================

    def setup_route(
        self,
        start_address: str,
        end_address:   str,
        condition:     Optional[RouteCondition] = None,
    ) -> Optional[Route]:
        """주소 기반으로 완전한 Route 객체를 생성한다.

        주소 → 좌표 변환 → 거리 계산 → 이동 수단 검증 → Route 생성 순서로 진행.

        Args:
            start_address: 출발지 주소 또는 랜드마크명
            end_address:   목적지 주소 또는 랜드마크명
            condition:     RouteCondition (None이면 기본값 사용)

        Returns:
            Route 객체 또는 실패 시 None
        """
        cond = condition or _DEFAULT_CONDITION
        self._logger.info("경로 설정 시작: '%s' → '%s'", start_address, end_address)

        # ── 좌표 조회 ───────────────────────────────────────────
        start_coords = self._resolve_coords(start_address)
        if start_coords is None:
            self._logger.warning("출발지 좌표 조회 실패: '%s'", start_address)
            return None

        end_coords = self._resolve_coords(end_address)
        if end_coords is None:
            self._logger.warning("목적지 좌표 조회 실패: '%s'", end_address)
            return None

        if start_coords == end_coords:
            self._logger.warning("출발지와 목적지 좌표가 동일합니다.")
            return None

        # ── 거리 계산 ───────────────────────────────────────────
        distance_m = self.kakao.calculate_distance(
            start_coords[0], start_coords[1],
            end_coords[0],   end_coords[1],
        )
        self._logger.debug(
            "거리 계산: %.0fm (%.2fkm)", distance_m, distance_m / 1000
        )

        # ── 이동 수단 검증 ──────────────────────────────────────
        if not self._validate_transport_mode(cond.transport_mode, distance_m):
            self._logger.warning(
                "이동 수단 부적합: %s / %.0fm",
                cond.transport_mode.value, distance_m,
            )

        # ── Route 객체 생성 ─────────────────────────────────────
        try:
            route = Route(
                start_address=start_address,
                end_address=end_address,
                start_coords=start_coords,
                end_coords=end_coords,
                distance=distance_m,
                condition=cond,
                created_at=datetime.now(),
            )
            route.validate()
        except ValueError as e:
            self._logger.error("Route 유효성 오류: %s", e)
            return None

        self.routes.append(route)
        self._logger.info(
            "경로 저장 완료: %s (총 %d개)", str(route), len(self.routes)
        )
        return route

    # =========================================================
    # 2. 자동 랜덤 경로 선택
    # =========================================================

    def auto_select_route(
        self,
        num_routes:   int   = 5,
        min_distance: float = 5_000,
        max_distance: float = 50_000,
        max_attempts: int   = 100,
        condition:    Optional[RouteCondition] = None,
    ) -> List[Route]:
        """랜드마크에서 조건에 맞는 랜덤 경로를 자동 선택한다.

        Args:
            num_routes:   목표 경로 수
            min_distance: 최소 거리 (미터)
            max_distance: 최대 거리 (미터)
            max_attempts: 최대 시도 횟수 (무한 루프 방지)
            condition:    RouteCondition (None이면 기본값)

        Returns:
            생성된 Route 리스트 (num_routes 이하일 수 있음)
        """
        cond     = condition or _DEFAULT_CONDITION
        names    = list(self.landmarks.keys())
        selected: List[Route] = []
        attempts  = 0

        self._logger.info(
            "자동 경로 선택 시작: 목표 %d개 / %.0fm~%.0fm",
            num_routes, min_distance, max_distance,
        )

        while len(selected) < num_routes and attempts < max_attempts:
            attempts += 1
            start_name, end_name = random.sample(names, 2)

            start_coords = self.landmarks[start_name]
            end_coords   = self.landmarks[end_name]

            dist = self.kakao.calculate_distance(
                start_coords[0], start_coords[1],
                end_coords[0],   end_coords[1],
            )

            if not (min_distance <= dist <= max_distance):
                self._logger.debug(
                    "[시도 %d] 거리 범위 외 (%.0fm): %s → %s",
                    attempts, dist, start_name, end_name,
                )
                continue

            # 랜드마크 좌표를 캐시된 주소 변환 없이 직접 Route 생성
            try:
                route = Route(
                    start_address=start_name,
                    end_address=end_name,
                    start_coords=start_coords,
                    end_coords=end_coords,
                    distance=dist,
                    condition=cond,
                    created_at=datetime.now(),
                )
                route.validate()
            except ValueError as e:
                self._logger.warning("Route 생성 실패 (시도 %d): %s", attempts, e)
                continue

            self.routes.append(route)
            selected.append(route)
            self._logger.info(
                "[%d/%d] %s → %s (%.1fkm)",
                len(selected), num_routes,
                start_name, end_name, dist / 1000,
            )

        if len(selected) < num_routes:
            self._logger.warning(
                "목표 %d개 미달: %d개 생성 (시도 %d회)",
                num_routes, len(selected), attempts,
            )
        else:
            self._logger.info(
                "자동 경로 선택 완료: %d개 생성 (시도 %d회)",
                len(selected), attempts,
            )

        return selected

    # =========================================================
    # 3. 이동 수단 거리 검증
    # =========================================================

    def _validate_transport_mode(
        self, mode: TransportMode, distance: float
    ) -> bool:
        """이동 수단별 적정 거리 범위를 검증한다.

        거리 기준:
            WALKING:  0 ~ 5km
            BICYCLE:  0 ~ 50km
            BUS:      1km 이상
            CAR:      제한 없음
            COMBINED: 3km 이상

        Args:
            mode:     TransportMode Enum
            distance: 거리 (미터)

        Returns:
            적절하면 True, 부적절하면 False
        """
        min_m, max_m = _MODE_DISTANCE.get(mode, (None, None))

        if min_m is not None and distance < min_m:
            self._logger.debug(
                "%s: 거리 %.0fm < 최소 %.0fm", mode.value, distance, min_m
            )
            return False
        if max_m is not None and distance > max_m:
            self._logger.debug(
                "%s: 거리 %.0fm > 최대 %.0fm", mode.value, distance, max_m
            )
            return False
        return True

    # =========================================================
    # 4. 경로 목록 출력 (tabulate)
    # =========================================================

    def print_routes(self) -> None:
        """저장된 경로를 테이블 형식으로 콘솔에 출력한다."""
        if not self.routes:
            print("저장된 경로가 없습니다.")
            return

        rows = [
            [
                idx + 1,
                r.start_address,
                r.end_address,
                f"{r.distance_km:.2f}km",
                r.condition.transport_mode.label(),
                r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ]
            for idx, r in enumerate(self.routes)
        ]

        headers = ["#", "출발지", "목적지", "거리", "이동수단", "생성시간"]
        print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        print(f"  총 {len(self.routes)}개 경로")

    # =========================================================
    # 5~7. CRUD
    # =========================================================

    def get_routes(self) -> List[Route]:
        """저장된 Route 리스트를 반환한다."""
        return list(self.routes)

    def clear_routes(self) -> None:
        """저장된 모든 경로를 삭제한다."""
        count = len(self.routes)
        self.routes.clear()
        self._logger.info("경로 %d개 삭제 완료", count)

    # =========================================================
    # 내부 유틸
    # =========================================================

    def _resolve_coords(self, name_or_address: str) -> Optional[Tuple[float, float]]:
        """랜드마크명이면 딕셔너리에서, 그 외엔 카카오 API로 좌표를 조회한다.

        lru_cache가 적용된 get_coords_from_address를 재사용해 중복 API 호출을 방지.
        """
        if name_or_address in self.landmarks:
            coords = self.landmarks[name_or_address]
            self._logger.debug(
                "랜드마크 좌표 사용: '%s' → %s", name_or_address, coords
            )
            return coords

        self._logger.debug("API 주소 변환 시도: '%s'", name_or_address)
        return self.kakao.get_coords_from_address(name_or_address)


class RouteSetup:
    """카카오 + T맵 + ODsay API를 초기화하고 경로를 조회하는 클래스.

    main.py 및 테스트에서 사용하는 간단한 퍼사드.
    config에서 API 키를 자동으로 읽어 핸들러를 생성한다.
    대중교통(bus) 모드는 ODsay API를 우선 사용한다.
    """

    def __init__(self) -> None:
        from config.api_config import config
        from core.odsay_api_handler import OdsayAPIHandler
        self.kakao   = KakaoAPIHandler(config.kakao.api_key)
        self.tmap    = TMapAPIHandler(config.tmap.api_key)
        self.odsay   = OdsayAPIHandler(config.odsay.api_key) if config.odsay else None
        self._logger = get_logger(self.__class__.__name__)
        if self.odsay:
            self._logger.info("ODsay API 초기화 완료 (대중교통/KTX 경로 지원)")
        else:
            self._logger.warning("ODsay API 키 미설정 — 대중교통 경로 불가 (.env에 ODSAY_API_KEY 추가 필요)")

    def fetch_both(
        self,
        origin:       Dict,
        destination:  Dict,
        vehicle_type: str  = "car",
        services:     list = None,
        preference:   str  = "optimal",
    ) -> Dict[str, RouteResult]:
        """선택된 지도 서비스의 경로를 조회하여 {provider: RouteResult} 형식으로 반환한다.

        Args:
            origin:       {"lat": float, "lon": float, ...}
            destination:  {"lat": float, "lon": float, ...}
            vehicle_type: 'car' | 'walk' | 'bike' | 'bus'
            services:     조회할 서비스 목록 (기본: ['kakao', 'tmap'])
            preference:   대중교통 경로 선택 기준 (bus 모드에서만 사용)
                          'optimal' | 'cheap' | 'fast' | 'comfort'

        Returns:
            {"kakao": RouteResult, "tmap": RouteResult, ...}
            조회 실패한 제공자는 결과에서 제외된다.
        """
        if services is None:
            services = ["kakao", "tmap"]

        start   = (origin["lat"],      origin["lon"])
        end     = (destination["lat"], destination["lon"])
        results: Dict[str, RouteResult] = {}

        # ── 대중교통 모드: ODsay API 사용 ───────────────────────
        if vehicle_type == "bus":
            if not self.odsay:
                raise ValueError(
                    "대중교통 경로 조회를 위해 ODsay API 키가 필요합니다. "
                    ".env 파일에 ODSAY_API_KEY를 추가해주세요. "
                    "(발급: https://lab.odsay.com)"
                )
            try:
                raw = self.odsay.get_transit_route(
                    start[0], start[1], end[0], end[1],
                    preference=preference,
                )
                if raw["distance_m"] == 0:
                    raise ValueError("대중교통 경로를 찾을 수 없습니다.")
                results["odsay"] = RouteResult(
                    provider="odsay",
                    distance_m=raw["distance_m"],
                    duration_s=raw["duration_s"],
                    toll_fee=raw["fare"],      # 대중교통 요금
                    transit_legs=raw["transit_legs"],
                    raw=raw,
                )
                self._logger.info(
                    "ODsay 대중교통 경로: %dm / %ds / %d원",
                    raw["distance_m"], raw["duration_s"], raw["fare"],
                )
            except Exception as e:
                self._logger.error("ODsay 경로 조회 실패: %s", e)
                raise

            # ── 자동차 비교 경로 (선택된 서비스 우선, 기본 카카오) ──
            car_svc = next((s for s in ["kakao", "tmap"] if s in services), "kakao")
            try:
                if car_svc == "tmap":
                    raw_car    = self.tmap.get_route(start, end, vehicle_type="car")
                    distance_m = int(raw_car.get("distance") or 0)
                    duration_s = int(raw_car.get("duration") or 0)
                    toll_fee   = int(raw_car.get("fare") or 0)
                    results["tmap"] = RouteResult(
                        provider="tmap",
                        distance_m=distance_m,
                        duration_s=duration_s,
                        toll_fee=toll_fee,
                        raw=raw_car,
                    )
                else:
                    raw_car    = self.kakao.get_route(start, end, vehicle_type="car")
                    distance_m = int(raw_car.get("distance") or 0)
                    duration_s = int(raw_car.get("duration") or 0)
                    routes     = raw_car.get("routes", [])
                    fare       = routes[0].get("summary", {}).get("fare", {}) if routes else {}
                    toll_fee   = int(fare.get("toll", 0)) if isinstance(fare, dict) else 0
                    taxi_fee   = int(fare.get("taxi", 0)) if isinstance(fare, dict) else 0
                    results["kakao"] = RouteResult(
                        provider="kakao",
                        distance_m=distance_m,
                        duration_s=duration_s,
                        toll_fee=toll_fee,
                        taxi_fee=taxi_fee,
                        raw=raw_car,
                    )
                self._logger.info("자동차 비교 경로(%s): %dm / %ds", car_svc, distance_m, duration_s)
            except Exception as e:
                self._logger.warning("자동차 비교 경로 조회 실패 — 대중교통 단독 표시: %s", e)

            return results

        # ── 자동차/도보/자전거 모드: 카카오 + T맵 ───────────────
        # 카카오 Mobility API는 자동차 전용 — 도보/자전거 모드에서는 제외
        _KAKAO_UNSUPPORTED = {"walk", "bike"}

        # ── 카카오 경로 조회 ────────────────────────────────────
        if "kakao" in services and vehicle_type not in _KAKAO_UNSUPPORTED:
            try:
                raw        = self.kakao.get_route(start, end, vehicle_type=vehicle_type)
                distance_m = int(raw.get("distance") or 0)
                duration_s = int(raw.get("duration") or 0)
                routes     = raw.get("routes", [])
                fare       = routes[0].get("summary", {}).get("fare", {}) if routes else {}
                toll_fee   = int(fare.get("toll", 0)) if isinstance(fare, dict) else 0
                taxi_fee   = int(fare.get("taxi", 0)) if isinstance(fare, dict) else 0
                results["kakao"] = RouteResult(
                    provider="kakao",
                    distance_m=distance_m,
                    duration_s=duration_s,
                    toll_fee=toll_fee,
                    taxi_fee=taxi_fee,
                    raw=raw,
                )
                self._logger.info("카카오 경로: %dm / %ds", distance_m, duration_s)
            except Exception as e:
                self._logger.error("카카오 경로 조회 실패: %s", e)

        # ── T맵 경로 조회 ───────────────────────────────────────
        if "tmap" in services:
            try:
                raw        = self.tmap.get_route(start, end, vehicle_type=vehicle_type)
                distance_m = int(raw.get("distance") or 0)
                duration_s = int(raw.get("duration") or 0)
                toll_fee   = int(raw.get("fare") or 0)
                results["tmap"] = RouteResult(
                    provider="tmap",
                    distance_m=distance_m,
                    duration_s=duration_s,
                    toll_fee=toll_fee,
                    raw=raw,
                )
                self._logger.info("T맵 경로: %dm / %ds", distance_m, duration_s)
            except Exception as e:
                self._logger.error("T맵 경로 조회 실패: %s", e)

        return results
