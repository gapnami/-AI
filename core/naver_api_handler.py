"""
네이버 클라우드 플랫폼 지도 API 핸들러 (구현 예정).

준비 사항:
    1. 네이버 클라우드 플랫폼 콘솔에서 아래 서비스 활성화
       - Maps / Directions 5 (경로 탐색)
       - Maps / Geocoding   (주소→좌표)
    2. Application 등록 후 Client ID / Client Secret 발급
    3. .env 에 아래 두 항목 추가:
         NAVER_CLIENT_ID=your_client_id
         NAVER_CLIENT_SECRET=your_client_secret
    4. 이 파일 하단 TODO 섹션을 완성하고 api_config.py 에 naver 설정 추가

API 레퍼런스:
    경로탐색 : GET https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving
               파라미터: start=lon,lat  goal=lon,lat  option=trafast|tracomfort|traavoidtoll
    지오코딩 : GET https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode
               파라미터: query=주소문자열
    역지오코딩: GET https://naveropenapi.apigw.ntruss.com/map-reversegeocode/v2/gc
               파라미터: coords=lon,lat  output=json  orders=roadaddr,addr
"""

import warnings
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

_DIRECTIONS_URL  = "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving"
_GEOCODE_URL     = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"
_REVERSE_GEO_URL = "https://naveropenapi.apigw.ntruss.com/map-reversegeocode/v2/gc"

# 경로 옵션 매핑 (vehicle_type → option 파라미터)
_OPTION_MAP = {
    "car":  "trafast",     # 실시간 빠른길
    "walk": "walking",     # 도보 (Directions15 API 별도)
    "bike": "cycling",     # 자전거
    "bus":  "trafast",     # 대중교통 미지원 → 자동차 fallback
}


class NaverAPIHandler:
    """네이버 클라우드 플랫폼 지도 API 래퍼.

    API 키 발급 후 __init__ 파라미터를 채우면 바로 활성화됩니다.

    Args:
        client_id:     네이버 클라우드 Client ID
        client_secret: 네이버 클라우드 Client Secret

    Example:
        >>> handler = NaverAPIHandler("client_id", "client_secret")
        >>> result = handler.get_route((37.5665, 126.9780), (37.4979, 127.0276))
        >>> result['distance'] > 0
        True
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            raise ValueError("네이버 Client ID와 Secret이 필요합니다.")
        self.client_id     = client_id
        self.client_secret = client_secret
        self.headers = {
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY":    client_secret,
            "Accept": "application/json",
        }
        self._logger = get_logger(self.__class__.__name__)
        self._logger.info("NaverAPIHandler 초기화 완료")

    # =========================================================================
    # 1. 경로 탐색
    # =========================================================================

    def get_route(
        self,
        start_coords: Tuple[float, float],
        end_coords:   Tuple[float, float],
        vehicle_type: str = "car",
    ) -> Dict:
        """출발지→목적지 경로를 탐색한다.

        Returns:
            {'distance': int(m), 'duration': int(s), 'toll_fee': int(원), 'raw': dict}

        TODO: API 키 획득 후 아래 주석 해제 및 구현 완성
        """
        import requests
        slat, slon = start_coords
        elat, elon = end_coords
        option = _OPTION_MAP.get(vehicle_type, "trafast")
        params = {
            "start":  f"{slon},{slat}",
            "goal":   f"{elon},{elat}",
            "option": option,
        }
        resp = requests.get(_DIRECTIONS_URL, headers=self.headers,
                            params=params, timeout=10, verify=False)
        resp.raise_for_status()
        raw  = resp.json()

        route   = raw["route"][option][0]
        summary = route["summary"]
        return {
            "distance": summary["distance"],           # 미터
            "duration": summary["duration"] // 1000,   # 밀리초 → 초
            "toll_fee": summary.get("tollFare", 0),
            "raw":      raw,
        }

    # =========================================================================
    # 2. 주소 → 좌표 변환
    # =========================================================================

    def get_coords_from_address(self, address: str) -> Optional[Tuple[float, float]]:
        """주소 문자열을 (위도, 경도) 튜플로 변환한다.

        TODO: API 키 획득 후 아래 주석 해제
        """
        import requests
        params = {"query": address}
        resp = requests.get(_GEOCODE_URL, headers=self.headers,
                            params=params, timeout=10, verify=False)
        resp.raise_for_status()
        items = resp.json().get("addresses", [])
        if not items:
            return None
        return float(items[0]["y"]), float(items[0]["x"])   # (위도, 경도)
