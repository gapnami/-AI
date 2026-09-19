"""
AHP (Analytic Hierarchy Process) - 계층적 분석 프로세스.

Saaty(1980) 9점 척도 기반 카카오맵 vs T맵 쌍대 비교 분석.

비교 척도:
  1  동등  /  3  약간 우수  /  5  우수  /  7  매우 우수  /  9  절대 우수
  짝수(2,4,6,8)는 중간값

RI 테이블 (Saaty 1987):
  n=1:0.00  n=2:0.00  n=3:0.58  n=4:0.90  n=5:1.12
  n=6:1.24  n=7:1.32  n=8:1.41  n=9:1.45  n=10:1.49
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from colorama import Fore, Style
from tabulate import tabulate

from utils.logger import get_logger

# ── 상수 ─────────────────────────────────────────────────────────────────────
_SERVICES: List[str] = ["카카오", "T맵"]
_SERVICE_KEY_MAP: Dict[str, str] = {
    "kakao": "카카오", "tmap": "T맵",
}

_CRITERIA: List[str] = [
    "coverage", "accuracy", "api_richness",
    "real_time_data", "route_optimization",
    "cost_efficiency", "developer_support",
]

_CRITERIA_LABELS: Dict[str, str] = {
    "coverage":           "지역커버리지",
    "accuracy":           "위치정확도",
    "api_richness":       "API기능다양성",
    "real_time_data":     "실시간데이터",
    "route_optimization": "경로최적화",
    "cost_efficiency":    "비용효율성",
    "developer_support":  "개발자지원",
}

# Saaty RI 테이블 (n: 1~10)
_RI: Dict[int, float] = {
    1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90,  5: 1.12,
    6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
}

_CR_THRESHOLD = 0.10   # 일관성 허용 한계


class AHPAnalyzer:
    """Saaty AHP 기반 지도 API 비교 분석기.

    Args:
        services:  비교 서비스 리스트 (기본: ['카카오', 'T맵'])
        criteria:  평가 기준 리스트 (기본: 7개 지표)

    Example:
        >>> analyzer = AHPAnalyzer()
        >>> matrix = analyzer.create_comparison_matrix({'kakao_vs_tmap': 5})
        >>> matrix.shape
        (2, 2)
        >>> matrix[0, 1]
        5.0
        >>> matrix[1, 0]
        0.2
    """

    def __init__(
        self,
        services: Optional[List[str]] = None,
        criteria: Optional[List[str]] = None,
    ) -> None:
        self.services = services or _SERVICES.copy()
        self.criteria = criteria or _CRITERIA.copy()
        self.ri_table = _RI.copy()
        self._n       = len(self.services)
        self._report: Dict[str, Any] = {}   # 마지막 rank_services 결과
        self._logger  = get_logger(self.__class__.__name__)
        self._logger.info(
            "AHPAnalyzer 초기화 | 서비스=%s | 기준=%d개",
            self.services, len(self.criteria),
        )

    # =========================================================
    # 내부 유틸
    # =========================================================

    def _key_to_service(self, key: str) -> str:
        """'kakao' → '카카오' 변환. 없으면 원본 반환."""
        return _SERVICE_KEY_MAP.get(key, key)

    def _parse_pair_key(self, pair_key: str) -> Tuple[int, int]:
        """'kakao_vs_tmap' → (0, 1) 서비스 인덱스 파싱."""
        parts = pair_key.split("_vs_")
        if len(parts) != 2:
            raise ValueError(f"쌍대 키 형식 오류: {pair_key!r}  (예: 'kakao_vs_tmap')")
        a_name = self._key_to_service(parts[0])
        b_name = self._key_to_service(parts[1])
        try:
            return self.services.index(a_name), self.services.index(b_name)
        except ValueError as e:
            raise ValueError(f"서비스명 오류: {e}") from e

    # =========================================================
    # 1. 쌍대 비교 행렬 생성
    # =========================================================

    def create_comparison_matrix(
        self, pairwise_comparisons: Dict[str, float]
    ) -> np.ndarray:
        """쌍대 비교 값(1-9 척도)으로 n×n 행렬을 생성한다.

        대각선=1, matrix[i][j] = value, matrix[j][i] = 1/value 자동 처리.

        Args:
            pairwise_comparisons: {'kakao_vs_tmap': 5, ...}
                값 > 1 : 앞 서비스가 뒤 서비스보다 우수
                값 = 1 : 동등
                0 < 값 < 1 : 뒤 서비스가 앞 서비스보다 우수

        Returns:
            n×n numpy float64 배열

        Raises:
            ValueError: 값이 0 이하이거나 키 형식 오류

        Example:
            >>> az = AHPAnalyzer()
            >>> m = az.create_comparison_matrix({'kakao_vs_tmap': 5})
            >>> round(m[1, 0], 4)
            0.2
        """
        n      = self._n
        matrix = np.eye(n, dtype=float)

        for pair_key, value in pairwise_comparisons.items():
            if value <= 0:
                raise ValueError(f"비교값은 양수여야 합니다: {pair_key}={value}")
            if value > 9:
                self._logger.warning("Saaty 척도 권장 범위 초과 (1-9): %s=%s", pair_key, value)

            i, j = self._parse_pair_key(pair_key)
            matrix[i, j] = float(value)
            matrix[j, i] = 1.0 / float(value)

        self._logger.debug("비교행렬 생성 완료:\n%s", matrix)
        return matrix

    # =========================================================
    # 2. 일관성 비율 계산
    # =========================================================

    def calculate_consistency_ratio(self, comparison_matrix: np.ndarray) -> float:
        """행렬의 일관성 비율(CR)을 계산한다.

        CR = CI / RI,  CI = (λ_max - n) / (n - 1)

        Args:
            comparison_matrix: create_comparison_matrix() 반환 행렬

        Returns:
            CR 값 (0.10 이하이면 일관성 우수)

        Example:
            >>> az = AHPAnalyzer()
            >>> m = az.create_comparison_matrix({'kakao_vs_tmap': 5})
            >>> az.calculate_consistency_ratio(m)
            0.0
        """
        n = comparison_matrix.shape[0]
        if n < 2:
            return 0.0
        if n == 2:
            self._logger.debug("n=2 행렬은 항상 CR=0.0")
            return 0.0

        eigenvalues = np.linalg.eigvals(comparison_matrix)
        lambda_max  = float(np.max(eigenvalues.real))

        ri = self.ri_table.get(n, 1.49)
        if ri == 0:
            return 0.0

        ci = (lambda_max - n) / (n - 1)
        cr = ci / ri
        self._logger.debug("λ_max=%.4f  CI=%.4f  RI=%.2f  CR=%.4f", lambda_max, ci, ri, cr)
        return float(cr)

    # =========================================================
    # 3. 가중치 계산 (고유벡터법)
    # =========================================================

    def calculate_weights(self, comparison_matrix: np.ndarray) -> Dict[str, float]:
        """최대 고유값에 해당하는 고유벡터로 정규화 가중치를 계산한다.

        Args:
            comparison_matrix: n×n 비교 행렬

        Returns:
            {'카카오': 0.833, 'T맵': 0.167} 형식 (합=1.0)

        Example:
            >>> az = AHPAnalyzer()
            >>> m = az.create_comparison_matrix({'kakao_vs_tmap': 5})
            >>> w = az.calculate_weights(m)
            >>> round(w['카카오'], 3)
            0.833
        """
        eigenvalues, eigenvectors = np.linalg.eig(comparison_matrix)
        max_idx    = int(np.argmax(eigenvalues.real))
        principal  = eigenvectors[:, max_idx].real

        # 모든 원소를 양수로 정규화
        principal  = np.abs(principal)
        normalized = principal / principal.sum()

        weights = {
            self.services[i]: round(float(normalized[i]), 6)
            for i in range(self._n)
        }
        self._logger.debug("가중치: %s", weights)
        return weights

    # =========================================================
    # 4. 일관성 검증
    # =========================================================

    def validate_consistency(self, cr: float) -> bool:
        """CR ≤ 0.10이면 일관성 우수로 판단한다.

        Args:
            cr: calculate_consistency_ratio() 반환값

        Returns:
            True이면 일관성 우수, False이면 재비교 필요
        """
        result = cr <= _CR_THRESHOLD
        level  = "우수" if result else "불량 (재비교 권장)"
        self._logger.debug("CR=%.4f → 일관성 %s", cr, level)
        return result

    # =========================================================
    # 5. 기준별 종합 순위 계산
    # =========================================================

    def rank_services(
        self,
        criteria: List[str],
        pairwise_comparisons: Dict[str, Dict[str, float]],
        criteria_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """각 기준별 쌍대 비교를 수행하고 종합 순위를 결정한다.

        Args:
            criteria:             평가 기준 리스트
            pairwise_comparisons: {'기준명': {'kakao_vs_tmap': 값}, ...}
            criteria_weights:     기준별 중요도 (None이면 균등 배분)

        Returns:
            {
                '카카오': float,  'T맵': float,
                'ranking': ['카카오', 'T맵'],
                'criteria_detail': {기준명: {'weights':..., 'cr':..., 'consistent':...}},
                'criteria_weights': {기준명: float},
            }

        Example:
            >>> az = AHPAnalyzer()
            >>> result = az.rank_services(
            ...     ['accuracy', 'speed'],
            ...     {'accuracy': {'kakao_vs_tmap': 5},
            ...      'speed':    {'kakao_vs_tmap': 3}},
            ... )
            >>> result['ranking'][0]
            '카카오'
        """
        if not criteria:
            raise ValueError("criteria가 비어 있습니다.")

        # 기준 가중치 설정 (균등 or 사용자 지정)
        if criteria_weights:
            total = sum(criteria_weights.values())
            cw    = {c: v / total for c, v in criteria_weights.items()}
        else:
            cw = {c: 1.0 / len(criteria) for c in criteria}

        self._logger.info("AHP 순위 계산 | 기준=%s", criteria)

        # 서비스별 최종 점수 초기화
        final_scores: Dict[str, float] = {s: 0.0 for s in self.services}
        criteria_detail: Dict[str, Any] = {}

        for criterion in criteria:
            comparisons = pairwise_comparisons.get(criterion, {})
            if not comparisons:
                self._logger.warning("기준 '%s'에 비교 데이터 없음 → 건너뜀", criterion)
                continue

            matrix     = self.create_comparison_matrix(comparisons)
            weights    = self.calculate_weights(matrix)
            cr         = self.calculate_consistency_ratio(matrix)
            consistent = self.validate_consistency(cr)

            if not consistent:
                self._logger.warning(
                    "기준 '%s' 일관성 불량: CR=%.4f (>0.10)", criterion, cr
                )

            w_c = cw.get(criterion, 1.0 / len(criteria))
            for service, w in weights.items():
                final_scores[service] += w * w_c

            criteria_detail[criterion] = {
                "weights":    weights,
                "cr":         round(cr, 4),
                "consistent": consistent,
                "criterion_weight": round(w_c, 4),
            }
            self._logger.debug(
                "기준 '%s': %s  CR=%.4f  기준가중치=%.4f",
                criterion, weights, cr, w_c,
            )

        # 정규화 (합=1)
        total = sum(final_scores.values())
        if total > 0:
            final_scores = {s: round(v / total, 6) for s, v in final_scores.items()}

        ranking = sorted(self.services, key=lambda s: final_scores[s], reverse=True)
        self._logger.info("AHP 최종 순위: %s", ranking)

        self._report = {
            **final_scores,
            "ranking":          ranking,
            "criteria_detail":  criteria_detail,
            "criteria_weights": cw,
        }
        return copy.deepcopy(self._report)

    # =========================================================
    # 6. AHP 보고서 반환
    # =========================================================

    def get_ahp_report(self) -> Dict[str, Any]:
        """마지막 rank_services() 결과의 상세 보고서를 반환한다.

        Returns:
            {
                '서비스별_종합점수':  {'카카오': float, 'T맵': float},
                '순위':              ['카카오', 'T맵'],
                '기준별_결과':        {기준명: {weights, cr, consistent, criterion_weight}},
                '기준_가중치':        {기준명: float},
                '일관성_요약':        {기준명: 'OK'|'재검토'},
            }

        Raises:
            RuntimeError: rank_services() 미실행 시
        """
        if not self._report:
            raise RuntimeError("rank_services()를 먼저 실행해야 합니다.")

        service_scores = {s: self._report[s] for s in self.services}
        consistency_summary = {
            c: ("OK" if d["consistent"] else "재검토 권장")
            for c, d in self._report["criteria_detail"].items()
        }

        return {
            "서비스별_종합점수": service_scores,
            "순위":             self._report["ranking"],
            "기준별_결과":       self._report["criteria_detail"],
            "기준_가중치":       self._report["criteria_weights"],
            "일관성_요약":       consistency_summary,
        }

    # =========================================================
    # 7. 콘솔 출력
    # =========================================================

    def print_ahp_analysis(self) -> None:
        """AHP 분석 결과를 색상 테이블로 콘솔에 출력한다."""
        if not self._report:
            print(f"{Fore.RED}rank_services()를 먼저 실행하세요.{Style.RESET_ALL}")
            return

        report = self.get_ahp_report()
        W      = 64

        def rule(c: str = "-") -> None:
            print(Fore.CYAN + c * W + Style.RESET_ALL)

        rule("=")
        print(Fore.CYAN + Style.BRIGHT + " AHP 분석 결과".center(W) + Style.RESET_ALL)
        rule("=")

        # ── 종합 순위 ─────────────────────────────────────────
        rank_rows = []
        for rank, svc in enumerate(report["순위"], 1):
            score  = report["서비스별_종합점수"][svc]
            medal  = {1: "1위", 2: "2위", 3: "3위"}.get(rank, f"{rank}위")
            color  = Fore.GREEN if rank == 1 else Fore.YELLOW if rank == 2 else Fore.WHITE
            rank_rows.append([
                f"{color}{medal}{Style.RESET_ALL}",
                f"{color}{svc}{Style.RESET_ALL}",
                f"{color}{score:.6f}{Style.RESET_ALL}",
            ])
        print(tabulate(rank_rows, headers=["순위", "서비스", "종합점수"],
                       tablefmt="rounded_outline"))
        rule()

        # ── 기준별 결과 ───────────────────────────────────────
        print(Fore.CYAN + " 기준별 비교 결과" + Style.RESET_ALL)
        detail_rows = []
        for criterion, d in report["기준별_결과"].items():
            label  = _CRITERIA_LABELS.get(criterion, criterion)
            cr_str = f"{d['cr']:.4f}"
            ok_str = f"{Fore.GREEN}OK{Style.RESET_ALL}" if d["consistent"] else f"{Fore.RED}재검토{Style.RESET_ALL}"
            svc_weights = "  /  ".join(
                f"{s}:{w:.4f}" for s, w in d["weights"].items()
            )
            detail_rows.append([label, svc_weights, cr_str, ok_str,
                                 f"{d['criterion_weight']:.4f}"])
        print(tabulate(
            detail_rows,
            headers=["기준", "서비스 가중치", "CR", "일관성", "기준가중치"],
            tablefmt="rounded_outline",
        ))
        rule()

        # ── RI 테이블 ─────────────────────────────────────────
        print(Fore.CYAN + " 내장 RI (Random Index) 테이블" + Style.RESET_ALL)
        ri_rows = [[n, ri] for n, ri in sorted(self.ri_table.items())]
        print(tabulate(ri_rows, headers=["n", "RI"], tablefmt="simple",
                       floatfmt=".2f"))
        rule("=")
