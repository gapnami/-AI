"""
ODsay LAB 대중교통 경로 API 핸들러.

버스·지하철·KTX 등 대중교통 경로를 탐색하고 구간별 세부 정보를 반환한다.
API 키 발급: https://lab.odsay.com
"""

import time
import urllib3
from urllib.parse import urlencode, quote_plus
from typing import Dict, List

import requests
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout, RequestException

from utils.logger import get_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL        = "https://api.odsay.com/v1/api"
_DEFAULT_TIMEOUT = 15
_MAX_RETRIES     = 3
_RETRY_DELAY     = 1.0

# ── 응답 캐시 (TTL 기반) ────────────────────────────────────────────────────
# 동일 좌표+선호도 조합 재호출 시 캐시에서 반환해 일일 쿼터 낭비 방지
_CACHE_TTL_SEC = 600          # 10분간 캐시 유지
_route_cache: dict = {}       # {cache_key: (timestamp, result)}

# ODsay trafficType: 1=지하철, 2=버스, 3=도보, 4=기차(KTX·SRT 등)
# 정의되지 않은 타입(5·6·7 등)은 미지원 교통 수단으로 오류 데이터를 포함할 수 있음
_VALID_TRAFFIC_TYPES = {1, 2, 3, 4}
_MAX_REALISTIC_SPEED_KMH = 350   # 지상 교통 현실적 최고속 (KTX 영업 최고 300 + 여유)

# trainType 코드 → 열차명 (trafficType=4 전용)
_TRAIN_TYPE_MAP = {
    1:   "KTX",
    2:   "새마을호",
    3:   "무궁화호",
    4:   "통근열차",
    5:   "바다열차",
    6:   "ITX-새마을",
    7:   "ITX-청춘",
    8:   "KTX",        # KTX 무정차·특별 편성 (ODsay 내부 코드)
    9:   "고속열차",
    100: "KTX-산천",
    101: "KTX-이음",
    900: "SRT",
}

# 지하철 lane name 기반 열차 판별 키워드 (trafficType=1 보조용)
_TRAIN_KEYWORDS = ("KTX", "SRT", "ITX", "무궁화", "새마을", "누리로", "열차", "KORAIL")


class OdsayAPIHandler:
    """ODsay LAB 대중교통 OPEN API 래퍼.

    Args:
        api_key: ODsay LAB (https://lab.odsay.com) 에서 발급받은 API 키

    Example:
        >>> handler = OdsayAPIHandler("your_api_key")
        >>> result = handler.get_transit_route(35.1150, 129.0416, 37.5546, 126.9706)
        >>> result['duration_s'] > 0
        True
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key는 비어 있을 수 없습니다.")
        self.api_key = api_key
        self._logger = get_logger(self.__class__.__name__)
        self._logger.debug("OdsayAPIHandler 초기화 완료")

    # =========================================================================
    # 내부 유틸리티
    # =========================================================================

    def _get(self, endpoint: str, params: dict) -> dict:
        """재시도 로직이 포함된 GET 요청."""
        url    = f"{_BASE_URL}/{endpoint}"
        params = {**params, "apiKey": self.api_key}
        last_exc = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                # 쿼리 문자열을 명시적으로 quote_plus로 인코딩하여
                # '+' 문자가 공백으로 잘못 해석되는 문제를 방지
                qs = urlencode(params, quote_via=quote_plus)
                full_url = f"{url}?{qs}"
                self._logger.debug(f"ODsay GET {full_url} (시도 {attempt})")
                resp = requests.get(full_url, timeout=_DEFAULT_TIMEOUT, verify=False)
                resp.raise_for_status()
                return resp.json()
            except ReadTimeout as e:
                last_exc = e
                self._logger.warning(f"타임아웃 (시도 {attempt})")
            except HTTPError as e:
                self._logger.error(f"HTTP 오류 {e.response.status_code}: {e.response.text[:200]}")
                raise
            except ConnectionError as e:
                last_exc = e
                self._logger.warning(f"연결 오류 (시도 {attempt}): {e}")
            except RequestException as e:
                self._logger.error(f"요청 오류: {e}")
                raise
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * attempt)
        raise last_exc  # type: ignore[misc]

    # =========================================================================
    # 대중교통 경로 탐색
    # =========================================================================

    def get_transit_route(
        self,
        start_lat: float, start_lon: float,
        end_lat:   float, end_lon:   float,
        preference: str = "optimal",
    ) -> Dict:
        """대중교통(버스·지하철·KTX 등) 경로를 탐색하고 구간별 정보를 반환한다.

        Args:
            start_lat:  출발지 위도
            start_lon:  출발지 경도
            end_lat:    목적지 위도
            end_lon:    목적지 경도
            preference: 경로 선택 기준
                        'optimal'  → ODsay 추천 첫 번째 경로 (기본값)
                        'cheap'    → 요금(totalPayment)이 가장 낮은 경로
                        'fast'     → 소요시간(totalTime)이 가장 짧은 경로
                        'comfort'  → 도보거리(totalWalk)가 가장 짧은 경로

        Returns:
            {
                'distance_m':    int,   # 총 이동거리 (m)
                'duration_s':    int,   # 총 소요시간 (초)
                'fare':          int,   # 총 요금 (원)
                'walk_distance': int,   # 총 도보 거리 (m)
                'transit_legs':  list,  # 구간별 세부 정보
                'raw':           dict,  # 원본 응답
            }

        Raises:
            RuntimeError: ODsay API 자체 오류 응답 시
        """
        self._logger.info(
            f"ODsay 대중교통 경로 탐색: ({start_lat},{start_lon}) → ({end_lat},{end_lon})"
            f" [preference={preference}]"
        )

        # ── 캐시 확인 ───────────────────────────────────────────────────────
        cache_key = (round(start_lat, 4), round(start_lon, 4),
                     round(end_lat,   4), round(end_lon,   4),
                     preference)
        cached = _route_cache.get(cache_key)
        if cached:
            ts, cached_result = cached
            if time.time() - ts < _CACHE_TTL_SEC:
                self._logger.info("ODsay 캐시 히트 — API 호출 생략")
                return cached_result
            else:
                del _route_cache[cache_key]

        raw = self._get("searchPubTransPathT", {
            "SX": start_lon, "SY": start_lat,
            "EX": end_lon,   "EY": end_lat,
        })

        # ODsay 에러 처리
        error = raw.get("error", [])
        if error:
            err_list = error if isinstance(error, list) else [error]
            err_info = err_list[0] if err_list else {}
            code     = str(err_info.get("code", ""))
            msg      = err_info.get("message", "ODsay 오류")

            # 쿼터 초과 → 사용자 친화적 메시지
            if code == "429" or "quota" in msg.lower() or "exceed" in msg.lower():
                raise RuntimeError(
                    "ODsay 일일 호출 한도 초과 — 내일 자정(00:00) 이후 재시도하거나 "
                    "lab.odsay.com에서 유료 플랜으로 업그레이드하세요."
                )
            raise RuntimeError(f"ODsay API 오류 [{code}]: {msg}")

        result = raw.get("result", {})
        paths  = result.get("path", [])

        if not paths:
            self._logger.warning("ODsay 경로 결과 없음")
            return {
                "distance_m": 0, "duration_s": 0,
                "fare": 0, "walk_distance": 0,
                "transit_legs": [], "raw": raw,
            }

        # ── 유효 경로 필터: 미정의 trafficType 및 물리적으로 불가능한 속도 제거 ──
        def _is_valid_path(p: dict) -> bool:
            sub_paths = p.get("subPath", [])
            info      = p.get("info", {})
            # 모든 subPath의 trafficType이 알려진 값인지 확인
            for sp in sub_paths:
                if int(sp.get("trafficType", 3)) not in _VALID_TRAFFIC_TYPES:
                    return False
            # 속도 현실성 검사: 이동거리(m) / 소요시간(분) → km/h
            dist_m  = int(info.get("totalDistance", 0))
            time_m  = int(info.get("totalTime", 1))
            if dist_m > 0 and time_m > 0:
                implied_speed = (dist_m / 1000) / (time_m / 60)
                if implied_speed > _MAX_REALISTIC_SPEED_KMH:
                    self._logger.warning(
                        "비현실적 경로 제외: %.0fkm/h (dist=%dm, time=%dmin)",
                        implied_speed, dist_m, time_m,
                    )
                    return False
            return True

        valid_paths = [p for p in paths if _is_valid_path(p)]
        if not valid_paths:
            self._logger.warning("유효 경로 없음 — 필터 전 전체 경로 사용")
            valid_paths = paths

        self._logger.info(
            "경로 필터: 전체 %d개 → 유효 %d개 (무효 %d개 제거)",
            len(paths), len(valid_paths), len(paths) - len(valid_paths),
        )

        # preference에 따라 최적 경로 선택
        _SORT_KEY = {
            "cheap":   lambda p: int(p.get("info", {}).get("totalPayment",
                                   p.get("info", {}).get("payment", 999_999))),
            "fast":    lambda p: int(p.get("info", {}).get("totalTime", 999_999)),
            "comfort": lambda p: int(p.get("info", {}).get("totalWalk", 999_999)),
        }
        sort_fn = _SORT_KEY.get(preference)
        best = min(valid_paths, key=sort_fn) if sort_fn else valid_paths[0]
        self._logger.debug(
            "경로 선택: preference=%s → 유효 %d개 중 선택",
            preference, len(valid_paths),
        )
        info     = best.get("info", {})
        total_min  = int(info.get("totalTime", 0))
        fare       = int(info.get("totalPayment", info.get("payment", 0)))
        dist_m     = int(info.get("totalDistance", 0))   # 단위: 미터
        walk_m     = int(info.get("totalWalk", 0))

        legs       = self._parse_legs(best.get("subPath", []))
        distance_m = dist_m if dist_m > 0 else walk_m

        self._logger.info(
            f"ODsay 결과: {total_min}분 / {fare:,}원 / {len(legs)}구간"
        )
        result_dict = {
            "distance_m":    distance_m,
            "duration_s":    total_min * 60,
            "fare":          fare,
            "walk_distance": walk_m,
            "transit_legs":  legs,
            "raw":           raw,
        }
        # 결과 캐시 저장
        _route_cache[cache_key] = (time.time(), result_dict)
        return result_dict

    # =========================================================================
    # 구간 파싱
    # =========================================================================

    @staticmethod
    def _parse_legs(sub_paths: list) -> List[dict]:
        """ODsay subPath 배열을 화면 표시용 구간 리스트로 변환한다.

        trafficType 코드:
            1: 지하철 / 광역전철
            2: 버스
            3: 도보
            4: 기차 (KTX / SRT / 무궁화 등) — trainType으로 세부 구분
        """
        legs = []
        for sub in sub_paths:
            t_type  = int(sub.get("trafficType", 3))
            sec_min = int(sub.get("sectionTime", 0))
            dist_m  = int(sub.get("distance", 0))
            dist_km = round(dist_m / 1000, 1) if dist_m >= 100 else round(float(sub.get("distance", 0)), 2)

            if t_type == 3:
                # 도보 구간
                legs.append({
                    "type":         "walk",
                    "type_label":   "도보",
                    "icon":         "🚶",
                    "duration_min": sec_min,
                    "distance_km":  dist_km,
                })

            elif t_type == 4:
                # 기차 구간 (KTX / SRT / 무궁화 등)
                train_type = int(sub.get("trainType", 1))
                line_name  = _TRAIN_TYPE_MAP.get(train_type, f"열차({train_type})")
                start_st   = sub.get("startName", "")
                end_st     = sub.get("endName", "")
                legs.append({
                    "type":          "train",
                    "type_label":    "열차",
                    "icon":          "🚄",
                    "line_name":     line_name,
                    "start_station": start_st,
                    "end_station":   end_st,
                    "station_count": 0,
                    "duration_min":  sec_min,
                    "distance_km":   dist_km,
                })

            else:
                lanes      = sub.get("lane", [])
                line_name  = lanes[0].get("name", "") if lanes else ""
                start_st   = sub.get("startName", "")
                end_st     = sub.get("endName", "")
                st_count   = int(sub.get("stationCount", 0))
                is_train   = any(k in line_name for k in _TRAIN_KEYWORDS)

                if t_type == 1:
                    leg_type  = "train"  if is_train else "subway"
                    leg_icon  = "🚄"     if is_train else "🚇"
                    leg_label = "열차"   if is_train else "지하철"
                else:
                    leg_type, leg_icon, leg_label = "bus", "🚌", "버스"

                legs.append({
                    "type":          leg_type,
                    "type_label":    leg_label,
                    "icon":          leg_icon,
                    "line_name":     line_name,
                    "start_station": start_st,
                    "end_station":   end_st,
                    "station_count": st_count,
                    "duration_min":  sec_min,
                    "distance_km":   round(dist_km, 2),
                })
        return legs
