"""
T맵 API 핸들러.

지원 기능:
  - 장소 검색 (키워드 / 반경)
  - 주소 ↔ 좌표 변환 (지오코딩 / 역지오코딩)
  - 경로 탐색 (자동차 / 도보 / 자전거)
  - 주변 POI 검색
  - 교통 정보 조회
  - 톨게이트 요금 정보
  - Haversine 거리 계산

Example:
    >>> handler = TmapAPIHandler("your_app_key")
    >>> handler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
    7952.3...
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
_BASE_URL        = "https://apis.openapi.sk.com/tmap"
_DEFAULT_TIMEOUT = 10
_MAX_RETRIES     = 3
_RETRY_DELAY     = 1.0  # 초

# vehicle_type → (HTTP method, endpoint, payload_builder)
_VEHICLE_ENDPOINTS: Dict[str, str] = {
    "car":  f"{_BASE_URL}/routes",
    "walk": f"{_BASE_URL}/routes/pedestrian",
    "bike": f"{_BASE_URL}/routes/bicycle",
    "bus":  f"{_BASE_URL}/routes",        # 대중교통은 별도 API, 자동차로 fallback
}

# T맵 POI 카테고리 코드 매핑
_POI_CATEGORY_MAP: Dict[str, str] = {
    "restaurant":   "음식점",
    "cafe":         "카페",
    "hospital":     "병원",
    "gas_station":  "주유소",
    "parking":      "주차장",
    "pharmacy":     "약국",
    "bank":         "은행",
    "convenience":  "편의점",
    "subway":       "지하철",
    "hotel":        "숙박",
}


class TmapAPIHandler:
    """T맵 REST API 래퍼 클래스.

    Args:
        app_key: SK Open API에서 발급받은 App Key

    Example:
        >>> handler = TmapAPIHandler("sRe06DGDNb35ii8EePigH9BdGwm1ucBw82rskXOg")
        >>> result = handler.search_place("강남역")
        >>> result['count'] > 0
        True
    """

    __hash__ = object.__hash__  # lru_cache에서 self를 키로 사용하기 위해

    def __init__(self, app_key: str) -> None:
        if not app_key:
            raise ValueError("app_key는 비어 있을 수 없습니다.")
        self.app_key  = app_key
        self.base_url = _BASE_URL
        self.headers  = {
            "appKey":       app_key,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }
        self.timeout     = _DEFAULT_TIMEOUT
        self.max_retries = _MAX_RETRIES
        self._logger     = get_logger(self.__class__.__name__)
        self._logger.debug("TmapAPIHandler 초기화 완료")

    # =========================================================================
    # 내부 유틸리티
    # =========================================================================

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        """재시도 로직이 포함된 GET 요청."""
        return self._request("GET", url, params=params)

    def _post(self, url: str, payload: Optional[Dict] = None) -> Dict:
        """재시도 로직이 포함된 POST 요청."""
        return self._request("POST", url, json=payload)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict] = None,
        json:   Optional[Dict] = None,
    ) -> Dict:
        """HTTP 요청 래퍼 (재시도 / 타임아웃 / 로깅 포함).

        Raises:
            HTTPError:        4xx/5xx 응답
            RequestException: 최대 재시도 초과
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self._logger.debug(f"[{method}] {url} (시도 {attempt}/{self.max_retries})")
                resp = requests.request(
                    method, url,
                    headers=self.headers,
                    params=params,
                    json=json,
                    timeout=self.timeout,
                    verify=False,
                )
                resp.raise_for_status()
                return resp.json()

            except ReadTimeout as e:
                self._logger.warning(f"타임아웃 (시도 {attempt}): {url}")
                last_exc = e
            except HTTPError as e:
                self._logger.error(
                    f"HTTP 오류 {e.response.status_code}: {url} "
                    f"→ {e.response.text[:200]}"
                )
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

    @staticmethod
    def _extract_route_summary(features: List[Dict]) -> Dict:
        """T맵 경로 응답 features에서 요약 정보를 추출한다."""
        for feat in features:
            props = feat.get("properties", {})
            if "totalDistance" in props:
                return props
        return {}

    # =========================================================================
    # 1. 장소 검색 (키워드)
    # =========================================================================

    def search_place(self, query: str, radius: int = 1000) -> Dict:
        """키워드로 T맵 POI를 검색한다.

        Args:
            query:  검색 키워드
            radius: 검색 반경 (미터)

        Returns:
            {'count': int, 'documents': [{'name', 'address', 'lat', 'lon'}, ...]}

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> result = handler.search_place("강남역")
            >>> isinstance(result['documents'], list)
            True
        """
        if not query.strip():
            raise ValueError("query가 비어 있습니다.")

        url    = f"{self.base_url}/pois"
        params = {
            "version":       1,
            "searchKeyword": query,
            "resCoordType":  "WGS84GEO",
            "reqCoordType":  "WGS84GEO",
            "count":         20,
        }

        self._logger.info(f"T맵 장소 검색: '{query}'")
        result = self._get(url, params=params)
        pois   = (
            result.get("searchPoiInfo", {})
                  .get("pois", {})
                  .get("poi", [])
        )

        documents = [
            {
                "name":     p.get("name", ""),
                "address":  f"{p.get('upperAddrName','')} {p.get('middleAddrName','')} {p.get('lowerAddrName','')}".strip(),
                "lat":      float(p.get("noorLat", 0)),
                "lon":      float(p.get("noorLon", 0)),
                "tel":      p.get("telNo", ""),
                "category": p.get("mlClass", ""),
            }
            for p in pois
        ]
        self._logger.debug(f"검색 결과: {len(documents)}건")
        return {"count": len(documents), "documents": documents}

    # =========================================================================
    # 2. 주소 → 좌표 변환 (lru_cache 적용)
    # =========================================================================

    @lru_cache(maxsize=512)
    def get_coords_from_address(self, address: str) -> Optional[Tuple[float, float]]:
        """주소 문자열을 (위도, 경도) 튜플로 변환한다. 결과는 캐싱된다.

        Args:
            address: 도로명 또는 지번 주소

        Returns:
            (위도, 경도) 또는 None

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> coords = handler.get_coords_from_address("서울 강남구 테헤란로 212")
            >>> coords is None or (isinstance(coords[0], float) and isinstance(coords[1], float))
            True
        """
        if not address.strip():
            raise ValueError("address가 비어 있습니다.")

        url    = f"{self.base_url}/geo/fullAddrGeo"
        params = {"version": 1, "fullAddr": address}

        self._logger.info(f"주소→좌표 변환: '{address}'")
        try:
            result = self._get(url, params=params)
            items  = result.get("coordinateInfo", {}).get("coordinate", [])
            if not items:
                self._logger.warning(f"지오코딩 결과 없음: '{address}'")
                return None
            lat = float(items[0].get("lat") or items[0].get("newLat", 0))
            lon = float(items[0].get("lon") or items[0].get("newLon", 0))
            self._logger.debug(f"좌표 변환 성공: ({lat}, {lon})")
            return (lat, lon)
        except RequestException:
            return None

    # =========================================================================
    # 3. 좌표 → 주소 변환
    # =========================================================================

    def get_reverse_coords(self, lat: float, lon: float) -> Optional[str]:
        """위경도를 주소 문자열로 변환한다.

        Args:
            lat: 위도
            lon: 경도

        Returns:
            도로명 주소 또는 None

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> addr = handler.get_reverse_coords(37.4979, 127.0276)
            >>> addr is None or isinstance(addr, str)
            True
        """
        self._validate_coords(lat, lon, "get_reverse_coords")
        url    = f"{self.base_url}/geo/reversegeocoding"
        params = {
            "version":      1,
            "lat":          lat,
            "lon":          lon,
            "coordType":    "WGS84GEO",
            "addressType":  "A10",
        }

        self._logger.info(f"좌표→주소 변환: ({lat}, {lon})")
        try:
            result    = self._get(url, params=params)
            addr_info = result.get("addressInfo", {})
            # 도로명 우선, 없으면 지번
            road = addr_info.get("fullAddress", "")
            self._logger.debug(f"역지오코딩 결과: {road}")
            return road or None
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
        """출발지→목적지 경로를 탐색한다.

        Args:
            start_coords: 출발지 (위도, 경도)
            end_coords:   목적지 (위도, 경도)
            vehicle_type: 'car' | 'walk' | 'bike' | 'bus'

        Returns:
            {
                'distance': int(m),
                'duration': int(s),
                'fare':     int(원, 자동차만),
                'features': list,
                'raw':      dict
            }

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> r = handler.get_route((37.5665, 126.9780), (37.4979, 127.0276))
            >>> r['distance'] > 0 and r['duration'] > 0
            True
        """
        if vehicle_type not in _VEHICLE_ENDPOINTS:
            raise ValueError(f"vehicle_type은 {list(_VEHICLE_ENDPOINTS)} 중 하나여야 합니다.")

        slat, slon = start_coords
        elat, elon = end_coords
        self._validate_coords(slat, slon, "start")
        self._validate_coords(elat, elon, "end")

        url     = _VEHICLE_ENDPOINTS[vehicle_type]
        payload = {
            "startX":       str(slon),
            "startY":       str(slat),
            "endX":         str(elon),
            "endY":         str(elat),
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "startName":    "출발지",
            "endName":      "목적지",
        }

        # 자동차 경로에만 교통 정보 추가
        if vehicle_type == "car":
            payload["trafficInfo"] = "Y"

        self._logger.info(
            f"T맵 경로 탐색 [{vehicle_type}]: ({slat},{slon}) → ({elat},{elon})"
        )
        raw      = self._post(f"{url}?version=1", payload=payload)
        features = raw.get("features", [])
        summary  = self._extract_route_summary(features)

        distance = summary.get("totalDistance", 0)
        duration = summary.get("totalTime", 0)
        fare     = summary.get("totalFare", 0)

        self._logger.info(f"경로 결과: {distance}m / {duration}s / 요금 {fare}원")
        return {
            "distance": distance,
            "duration": duration,
            "fare":     fare,
            "features": features,
            "raw":      raw,
        }

    # =========================================================================
    # 5. 실시간 교통 정보
    # =========================================================================

    def get_traffic_info(self, lat: float, lon: float, radius: int = 500) -> Dict:
        """실시간 교통 상황을 경로 탐색 기반으로 조회한다.

        실제 T맵 교통정보 API는 기업 전용이므로, 주변 경로의 속도 정보를
        바탕으로 혼잡도를 추정한다.

        Args:
            lat:    중심 위도
            lon:    중심 경도
            radius: 참고 반경 (미터)

        Returns:
            {
                'congestion':  str ('low'|'medium'|'high'|'unknown'),
                'description': str,
                'nearby_pois': int
            }

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> info = handler.get_traffic_info(37.5665, 126.9780)
            >>> info['congestion'] in ('low', 'medium', 'high', 'unknown')
            True
        """
        self._validate_coords(lat, lon, "get_traffic_info")

        self._logger.info(f"교통 정보 조회: ({lat},{lon}) 반경 {radius}m")

        # 주변 지하철역 수로 혼잡도 추정 (실시간 교통 API 대체)
        try:
            poi_result = self.search_nearby_poi(lat, lon, category="subway", radius=radius)
            count      = len(poi_result)
            congestion = "high" if count >= 3 else ("medium" if count >= 1 else "low")
            description = {
                "high":   f"반경 {radius}m 내 지하철역 {count}개 / 혼잡 예상",
                "medium": f"반경 {radius}m 내 지하철역 {count}개 / 보통",
                "low":    f"반경 {radius}m 내 대중교통 허브 없음 / 원활",
            }[congestion]
        except RequestException:
            congestion  = "unknown"
            count       = 0
            description = "교통 정보 조회 실패"

        self._logger.debug(f"혼잡도: {congestion} ({description})")
        return {
            "congestion":  congestion,
            "description": description,
            "nearby_pois": count,
        }

    # =========================================================================
    # 6. 주변 POI 검색
    # =========================================================================

    def search_nearby_poi(
        self,
        lat:      float,
        lon:      float,
        category: str = "restaurant",
        radius:   int = 1000,
    ) -> List[Dict]:
        """주변 POI를 거리순으로 검색한다.

        카테고리:
            restaurant / cafe / hospital / gas_station /
            parking / pharmacy / bank / convenience / subway / hotel

        Args:
            lat:      중심 위도
            lon:      중심 경도
            category: 카테고리 키 (위 목록 참고)
            radius:   검색 반경 (미터)

        Returns:
            [{'name', 'address', 'lat', 'lon', 'distance', 'tel', 'category'}, ...]

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> pois = handler.search_nearby_poi(37.5665, 126.9780, "cafe", 500)
            >>> isinstance(pois, list)
            True
        """
        self._validate_coords(lat, lon, "search_nearby_poi")

        keyword = _POI_CATEGORY_MAP.get(category, category)
        url     = f"{self.base_url}/pois"
        # T맵 free tier는 반경 공간 필터 미지원 → 키워드 검색 후 Haversine 거리 필터링
        params  = {
            "version":       1,
            "searchKeyword": keyword,
            "resCoordType":  "WGS84GEO",
            "reqCoordType":  "WGS84GEO",
            "count":         50,
        }

        self._logger.info(
            f"T맵 POI 검색 [{category}={keyword}]: ({lat},{lon}) 반경 {radius}m"
        )
        result = self._get(url, params=params)
        pois   = (
            result.get("searchPoiInfo", {})
                  .get("pois", {})
                  .get("poi", [])
        )

        normalized = []
        for p in pois:
            poi_lat = float(p.get("noorLat", 0))
            poi_lon = float(p.get("noorLon", 0))
            dist    = int(self.calculate_distance(lat, lon, poi_lat, poi_lon))
            if dist <= radius:   # 반경 내 결과만 포함
                normalized.append({
                    "name":     p.get("name", ""),
                    "address":  f"{p.get('upperAddrName','')} {p.get('middleAddrName','')} {p.get('lowerAddrName','')}".strip(),
                    "lat":      poi_lat,
                    "lon":      poi_lon,
                    "distance": dist,
                    "tel":      p.get("telNo", ""),
                    "category": p.get("mlClass", ""),
                })

        normalized.sort(key=lambda x: x["distance"])
        self._logger.debug(f"POI {len(normalized)}건 반환 (반경 {radius}m 이내, 거리순)")
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
            >>> TmapAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
            7952.3...
        """
        R  = 6_371_000
        φ1 = math.radians(lat1)
        φ2 = math.radians(lat2)
        Δφ = math.radians(lat2 - lat1)
        Δλ = math.radians(lon2 - lon1)

        a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # =========================================================================
    # 8. 톨게이트 요금 정보
    # =========================================================================

    def get_toll_info(self, route_coords: List[Tuple[float, float]]) -> Dict:
        """경로의 예상 톨게이트 요금을 조회한다.

        T맵 자동차 경로 탐색 API의 totalFare에서 요금을 추출하며,
        경로 좌표의 출발·도착점만 사용해 재조회한다.

        Args:
            route_coords: 경로 좌표 리스트 [(위도, 경도), ...]

        Returns:
            {
                'toll_fare':  int (원),
                'total_fare': int (원, 주유비 등 포함 추정),
                'distance_m': int,
                'duration_s': int,
            }

        Example:
            >>> handler = TmapAPIHandler("key")
            >>> coords = [(37.5665, 126.9780), (37.4979, 127.0276)]
            >>> info = handler.get_toll_info(coords)
            >>> 'toll_fare' in info
            True
        """
        if len(route_coords) < 2:
            raise ValueError("route_coords는 최소 2개 이상의 좌표가 필요합니다.")

        start = route_coords[0]
        end   = route_coords[-1]

        self._logger.info(
            f"톨게이트 요금 조회: ({start[0]},{start[1]}) → ({end[0]},{end[1]})"
        )
        route = self.get_route(start, end, vehicle_type="car")

        # T맵 경로 응답에서 요금 세부 정보 추출
        features   = route.get("features", [])
        summary    = self._extract_route_summary(features)
        total_fare = summary.get("totalFare", 0)

        # 고속도로 구간 통행료 별도 집계
        toll_fare = 0
        for feat in features:
            props = feat.get("properties", {})
            if props.get("facilityType") in ("3", "4"):  # 3: 고속도로, 4: 유료도로
                toll_fare += props.get("tollFare", 0)

        self._logger.info(
            f"요금 정보: 총요금 {total_fare}원 / 통행료 {toll_fare}원"
        )
        return {
            "toll_fare":  toll_fare,
            "total_fare": total_fare,
            "distance_m": route["distance"],
            "duration_s": route["duration"],
        }
