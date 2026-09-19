"""
카카오맵 API 핸들러.

지원 기능:
  - 장소 검색 (키워드 / 카테고리)
  - 주소 ↔ 좌표 변환
  - 경로 탐색 (자동차 / 도보 / 자전거)
  - 주변 POI 검색
  - 교통 정보 조회
  - Haversine 거리 계산

Example:
    >>> handler = KakaoAPIHandler("your_api_key")
    >>> handler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
    7952.0  # 약 7.9km
"""

import math
import time
import urllib3
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import requests
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout, RequestException

from utils.logger import get_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 상수 ─────────────────────────────────────────────────────────────────────
_LOCAL_BASE_URL  = "https://dapi.kakao.com/v2/local"
_NAVI_BASE_URL   = "https://apis-navi.kakaomobility.com/v1"
_DEFAULT_TIMEOUT = 10
_MAX_RETRIES     = 3
_RETRY_DELAY     = 1.0   # 초

_VEHICLE_ROUTE_MAP = {
    "car":  f"{_NAVI_BASE_URL}/directions",
    "walk": f"{_NAVI_BASE_URL}/directions",   # 카카오 도보 동일 endpoint, priority 변경
    "bike": f"{_NAVI_BASE_URL}/directions",
    "bus":  f"{_NAVI_BASE_URL}/directions",
}


class KakaoAPIHandler:
    """카카오맵 REST API 래퍼 클래스.

    Args:
        api_key: 카카오 REST API 키 (KakaoAK 인증)

    Example:
        >>> handler = KakaoAPIHandler("df11e4e67fcb9b4a2f708f1c2591fed9")
        >>> result = handler.search_place("강남역")
        >>> result['meta']['total_count'] > 0
        True
    """

    # lru_cache가 self를 키로 사용할 수 있도록 id 기반 해시 유지
    __hash__ = object.__hash__

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key는 비어 있을 수 없습니다.")
        self.api_key   = api_key
        self.base_url  = _LOCAL_BASE_URL
        self.navi_url  = _NAVI_BASE_URL
        self.headers   = {
            "Authorization": f"KakaoAK {api_key}",
            "Accept":        "application/json",
        }
        self.timeout    = _DEFAULT_TIMEOUT
        self.max_retries = _MAX_RETRIES
        self._logger    = get_logger(self.__class__.__name__)
        self._logger.debug("KakaoAPIHandler 초기화 완료")

    # =========================================================================
    # 내부 유틸리티
    # =========================================================================

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
    ) -> Dict:
        """재시도 로직이 포함된 HTTP 요청 래퍼.

        Raises:
            requests.RequestException: 최대 재시도 횟수 초과 시
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self._logger.debug(f"[{method}] {url} (시도 {attempt}/{self.max_retries})")
                response = requests.request(
                    method, url,
                    headers=self.headers,
                    params=params,
                    json=json,
                    timeout=self.timeout,
                    verify=False,
                )
                response.raise_for_status()
                return response.json()

            except ReadTimeout as e:
                self._logger.warning(f"타임아웃 (시도 {attempt}): {url}")
                last_exc = e
            except HTTPError as e:
                # 4xx 는 재시도해도 의미 없음
                self._logger.error(f"HTTP 오류 {e.response.status_code}: {url} → {e.response.text[:200]}")
                raise
            except ConnectionError as e:
                self._logger.warning(f"연결 오류 (시도 {attempt}): {e}")
                last_exc = e
            except RequestException as e:
                self._logger.error(f"요청 오류: {e}")
                raise

            if attempt < self.max_retries:
                time.sleep(_RETRY_DELAY * attempt)

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _validate_coords(lat: float, lon: float, label: str = "") -> None:
        prefix = f"[{label}] " if label else ""
        if not (-90 <= lat <= 90):
            raise ValueError(f"{prefix}위도 범위 오류: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"{prefix}경도 범위 오류: {lon}")

    # =========================================================================
    # 1. 장소 검색 (키워드)
    # =========================================================================

    def search_place(
        self,
        query: str,
        page: int = 1,
        size: int = 15,
    ) -> Dict:
        """키워드로 장소를 검색한다.

        Args:
            query: 검색 키워드
            page:  페이지 번호 (1~45)
            size:  페이지당 결과 수 (1~15)

        Returns:
            {'documents': [...], 'meta': {'total_count': int, ...}}

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> result = handler.search_place("강남역", size=5)
            >>> isinstance(result['documents'], list)
            True
        """
        if not query.strip():
            raise ValueError("query가 비어 있습니다.")
        if not (1 <= page <= 45):
            raise ValueError(f"page는 1~45 범위여야 합니다: {page}")
        if not (1 <= size <= 15):
            raise ValueError(f"size는 1~15 범위여야 합니다: {size}")

        url    = f"{self.base_url}/search/keyword.json"
        params = {"query": query, "page": page, "size": size}

        self._logger.info(f"장소 검색: '{query}' (page={page})")
        result = self._request("GET", url, params=params)
        count  = result.get("meta", {}).get("total_count", 0)
        self._logger.debug(f"검색 결과: {count}건")
        return result

    # =========================================================================
    # 2. 주소 → 좌표 변환 (lru_cache 적용)
    # =========================================================================

    @lru_cache(maxsize=512)
    def get_coords_from_address(self, address: str) -> Optional[Tuple[float, float]]:
        """주소 문자열을 (위도, 경도) 튜플로 변환한다. 결과는 캐싱된다.

        Args:
            address: 도로명 또는 지번 주소

        Returns:
            (위도, 경도) 또는 검색 결과 없을 시 None

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> coords = handler.get_coords_from_address("강남구 테헤란로 212")
            >>> coords is None or (isinstance(coords[0], float) and isinstance(coords[1], float))
            True
        """
        if not address.strip():
            raise ValueError("address가 비어 있습니다.")

        url    = f"{self.base_url}/search/address.json"
        params = {"query": address, "size": 1}

        self._logger.info(f"주소→좌표 변환: '{address}'")
        try:
            result = self._request("GET", url, params=params)
            docs   = result.get("documents", [])
            if not docs:
                self._logger.warning(f"주소 검색 결과 없음: '{address}'")
                return None
            x, y = float(docs[0]["x"]), float(docs[0]["y"])   # x=경도, y=위도
            self._logger.debug(f"좌표 변환 성공: ({y}, {x})")
            return (y, x)  # (위도, 경도)
        except RequestException:
            return None

    # =========================================================================
    # 3. 좌표 → 주소 변환
    # =========================================================================

    def get_reverse_coords(self, lat: float, lon: float) -> Optional[str]:
        """위경도 좌표를 주소 문자열로 변환한다.

        Args:
            lat: 위도
            lon: 경도

        Returns:
            도로명 주소 문자열, 없으면 None

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> addr = handler.get_reverse_coords(37.4979, 127.0276)
            >>> addr is None or isinstance(addr, str)
            True
        """
        self._validate_coords(lat, lon, "get_reverse_coords")
        url    = f"{self.base_url}/geo/coord2address.json"
        params = {"x": lon, "y": lat, "input_coord": "WGS84"}

        self._logger.info(f"좌표→주소 변환: ({lat}, {lon})")
        try:
            result = self._request("GET", url, params=params)
            docs   = result.get("documents", [])
            if not docs:
                self._logger.warning(f"역지오코딩 결과 없음: ({lat}, {lon})")
                return None
            road = docs[0].get("road_address")
            addr = docs[0].get("address")
            name = (road or addr or {}).get("address_name")
            self._logger.debug(f"주소 변환 성공: {name}")
            return name
        except RequestException:
            return None

    # =========================================================================
    # 4. 경로 탐색
    # =========================================================================

    def get_route(
        self,
        start_coords: Tuple[float, float],
        end_coords:   Tuple[float, float],
        vehicle_type: str = "car",
    ) -> Dict:
        """출발지→목적지 경로 정보를 조회한다.

        Args:
            start_coords: 출발지 (위도, 경도)
            end_coords:   목적지 (위도, 경도)
            vehicle_type: 'car' | 'walk' | 'bike' | 'bus'

        Returns:
            {'distance': int(m), 'duration': int(s), 'routes': list, 'raw': dict}

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> result = handler.get_route((37.5665, 126.9780), (37.4979, 127.0276))
            >>> 'distance' in result and 'duration' in result
            True
        """
        if vehicle_type not in _VEHICLE_ROUTE_MAP:
            raise ValueError(f"vehicle_type은 {list(_VEHICLE_ROUTE_MAP)} 중 하나여야 합니다.")

        slat, slon = start_coords
        elat, elon = end_coords
        self._validate_coords(slat, slon, "start")
        self._validate_coords(elat, elon, "end")

        url    = _VEHICLE_ROUTE_MAP[vehicle_type]
        params = {
            "origin":      f"{slon},{slat}",
            "destination": f"{elon},{elat}",
            "priority":    "RECOMMEND",
        }

        self._logger.info(f"경로 탐색 [{vehicle_type}]: ({slat},{slon}) → ({elat},{elon})")
        raw    = self._request("GET", url, params=params)
        routes = raw.get("routes", [])

        if not routes:
            self._logger.warning("경로 탐색 결과 없음")
            return {"distance": 0, "duration": 0, "routes": [], "raw": raw}

        result_code = routes[0].get("result_code", 0)
        result_msg  = routes[0].get("result_msg", "")
        if result_code != 0:
            self._logger.warning("카카오 경로 result_code=%d: %s", result_code, result_msg)

        summary  = routes[0].get("summary", {})
        distance = summary.get("distance", 0)
        duration = summary.get("duration", 0)
        self._logger.info("경로 결과: %dm / %ds (code=%d)", distance, duration, result_code)
        return {
            "distance":    distance,
            "duration":    duration,
            "result_code": result_code,
            "result_msg":  result_msg,
            "routes":      routes,
            "raw":         raw,
        }

    # =========================================================================
    # 5. 실시간 교통 정보
    # =========================================================================

    def get_traffic_info(self, lat: float, lon: float, radius: int = 500) -> Dict:
        """주변 대중교통(지하철역·버스정류장) 밀도로 교통 혼잡도를 추정한다.

        카카오 카테고리 기준:
            SW8: 지하철역 / BK9: 은행(환승 허브 근접도 참고용)

        Args:
            lat:    중심 위도
            lon:    중심 경도
            radius: 검색 반경 (미터, 최대 20000)

        Returns:
            {'count': int, 'congestion': str, 'documents': list}
            congestion: 'low' | 'medium' | 'high'

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> info = handler.get_traffic_info(37.5665, 126.9780, 500)
            >>> 'count' in info and 'congestion' in info
            True
        """
        self._validate_coords(lat, lon, "get_traffic_info")
        if not (0 < radius <= 20000):
            raise ValueError(f"radius는 1~20000 범위여야 합니다: {radius}")

        url    = f"{self.base_url}/search/category.json"
        params = {
            "category_group_code": "SW8",   # 지하철역 (TC는 카카오 미지원)
            "x": lon, "y": lat,
            "radius": radius,
            "sort": "distance",
        }

        self._logger.info(f"교통 정보 조회: ({lat},{lon}) 반경 {radius}m")
        try:
            result = self._request("GET", url, params=params)
        except HTTPError:
            self._logger.warning("교통 카테고리 조회 실패, 빈 결과 반환")
            return {"count": 0, "congestion": "unknown", "documents": []}

        docs = result.get("documents", [])
        # 지하철역 수로 간단 혼잡도 추정
        count = len(docs)
        congestion = "high" if count >= 3 else ("medium" if count >= 1 else "low")
        self._logger.debug(f"지하철역 {count}건 → 혼잡도: {congestion}")
        return {"count": count, "congestion": congestion, "documents": docs}

    # =========================================================================
    # 6. 주변 POI 검색
    # =========================================================================

    def search_nearby_poi(
        self,
        lat:      float,
        lon:      float,
        category: str = "CE7",
        radius:   int = 1000,
    ) -> List[Dict]:
        """주변 POI(관심 지점)를 거리순으로 검색한다.

        카테고리 코드:
            CE7: 카페  /  FD6: 음식점  /  PM9: 약국
            HP8: 병원  /  OL7: 주유소  /  PK6: 주차장

        Args:
            lat:      중심 위도
            lon:      중심 경도
            category: 카카오 카테고리 코드
            radius:   검색 반경 (미터)

        Returns:
            [{'name', 'address', 'x', 'y', 'distance', 'phone', 'url'}, ...]

        Example:
            >>> handler = KakaoAPIHandler("key")
            >>> pois = handler.search_nearby_poi(37.5665, 126.9780, "CE7", 500)
            >>> isinstance(pois, list)
            True
        """
        self._validate_coords(lat, lon, "search_nearby_poi")

        url    = f"{self.base_url}/search/category.json"
        params = {
            "category_group_code": category,
            "x": lon, "y": lat,
            "radius": radius,
            "sort": "distance",
            "size": 15,
        }

        self._logger.info(f"주변 POI 검색 [{category}]: ({lat},{lon}) 반경 {radius}m")
        result = self._request("GET", url, params=params)
        docs   = result.get("documents", [])

        normalized = [
            {
                "name":     d.get("place_name", ""),
                "address":  d.get("road_address_name") or d.get("address_name", ""),
                "x":        float(d.get("x", 0)),
                "y":        float(d.get("y", 0)),
                "distance": int(d.get("distance", 0)),
                "phone":    d.get("phone", ""),
                "url":      d.get("place_url", ""),
                "category": d.get("category_name", ""),
            }
            for d in docs
        ]
        self._logger.debug(f"POI {len(normalized)}건 반환")
        return normalized

    # =========================================================================
    # 7. Haversine 거리 계산
    # =========================================================================

    @staticmethod
    def calculate_distance(
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        """Haversine 공식으로 두 좌표 사이의 거리를 계산한다.

        Args:
            lat1, lon1: 출발 위경도 (도 단위)
            lat2, lon2: 도착 위경도 (도 단위)

        Returns:
            거리 (미터)

        Example:
            >>> KakaoAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
            7952.322...
        """
        R = 6_371_000  # 지구 반지름 (미터)

        φ1, φ2   = math.radians(lat1), math.radians(lat2)
        Δφ       = math.radians(lat2 - lat1)
        Δλ       = math.radians(lon2 - lon1)

        a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c
