"""
API 응답 속도 벤치마크 엔진.

카카오맵 / T맵 API 호출 시간을 반복 측정해 평균·최소·최대를 반환한다.
"""

import time
from typing import Dict, List, Optional, Tuple

from core.kakao_api_handler import KakaoAPIHandler
from core.tmap_api_handler import TmapAPIHandler
from config.api_config import config
from utils.logger import get_logger

logger = get_logger(__name__)

# 기본 테스트 경로 (서울시청 → 강남역)
_DEFAULT_START = (37.5665, 126.9780)
_DEFAULT_END   = (37.4979, 127.0276)


class BenchmarkEngine:
    """카카오맵 / T맵 경로 API 응답 속도 벤치마크.

    Args:
        kakao_handler: KakaoAPIHandler 인스턴스 (None이면 자동 생성)
        tmap_handler:  TmapAPIHandler  인스턴스 (None이면 자동 생성)

    Example:
        >>> engine = BenchmarkEngine()
        >>> result = engine.run(iterations=2)
        >>> 'kakao' in result and 'tmap' in result
        True
    """

    def __init__(
        self,
        kakao_handler: Optional[KakaoAPIHandler] = None,
        tmap_handler:  Optional[TmapAPIHandler]  = None,
    ) -> None:
        self.kakao = kakao_handler or KakaoAPIHandler(config.kakao.api_key)
        self.tmap  = tmap_handler  or TmapAPIHandler(config.tmap.api_key)
        self._results: Dict[str, List[float]] = {"kakao": [], "tmap": []}

    def run(
        self,
        start_coords: Tuple[float, float] = _DEFAULT_START,
        end_coords:   Tuple[float, float] = _DEFAULT_END,
        iterations:   int = 5,
        vehicle_type: str = "car",
    ) -> Dict[str, Dict]:
        """경로 API를 반복 호출해 응답 시간을 측정한다.

        Args:
            start_coords: 출발지 (위도, 경도)
            end_coords:   목적지 (위도, 경도)
            iterations:   반복 횟수
            vehicle_type: 경로 유형 ('car' | 'walk')

        Returns:
            {
                'kakao': {'avg_s': float, 'min_s': float, 'max_s': float, 'samples': int},
                'tmap':  { ... },
            }
        """
        timings: Dict[str, List[float]] = {"kakao": [], "tmap": []}

        for i in range(1, iterations + 1):
            logger.info("벤치마크 반복 %d/%d", i, iterations)

            # ── 카카오 ───────────────────────────────────────
            try:
                t0 = time.perf_counter()
                self.kakao.get_route(start_coords, end_coords, vehicle_type=vehicle_type)
                timings["kakao"].append(time.perf_counter() - t0)
            except Exception as e:
                logger.warning("카카오 호출 실패 (반복 %d): %s", i, e)

            # ── T맵 ─────────────────────────────────────────
            try:
                t0 = time.perf_counter()
                self.tmap.get_route(start_coords, end_coords, vehicle_type=vehicle_type)
                timings["tmap"].append(time.perf_counter() - t0)
            except Exception as e:
                logger.warning("T맵 호출 실패 (반복 %d): %s", i, e)

        self._results = timings
        return self._summarize(timings)

    @staticmethod
    def _summarize(timings: Dict[str, List[float]]) -> Dict[str, Dict]:
        summary = {}
        for provider, times in timings.items():
            if times:
                summary[provider] = {
                    "avg_s":   round(sum(times) / len(times), 4),
                    "min_s":   round(min(times), 4),
                    "max_s":   round(max(times), 4),
                    "samples": len(times),
                }
            else:
                summary[provider] = {
                    "avg_s": None, "min_s": None, "max_s": None, "samples": 0
                }
        return summary

    def print_results(self) -> None:
        """마지막 벤치마크 결과를 콘솔에 출력한다."""
        summary = self._summarize(self._results)
        print(f"\n{'='*44}")
        print(f"  API 응답 속도 벤치마크 결과")
        print(f"{'='*44}")
        for provider, s in summary.items():
            if s["samples"]:
                print(f"  [{provider.upper():6s}] "
                      f"평균={s['avg_s']:.3f}s  "
                      f"최소={s['min_s']:.3f}s  "
                      f"최대={s['max_s']:.3f}s  "
                      f"({s['samples']}회)")
            else:
                print(f"  [{provider.upper():6s}] 측정값 없음")
        print(f"{'='*44}\n")
