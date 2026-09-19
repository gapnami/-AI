"""
가중치 기반 지도 API 평가 시스템.

평가 지표 (7개):
  coverage          지역 커버리지          0.15
  accuracy          위치 정확도            0.20
  api_richness      API 기능 다양성         0.15
  real_time_data    실시간 데이터 갱신       0.20
  route_optimization 경로 최적화 성능       0.15
  cost_efficiency   비용 효율성             0.10
  developer_support 개발자 지원             0.05
"""

import copy
import json
from typing import Dict, List, Optional

import pandas as pd
from colorama import Fore, Style
from sklearn.preprocessing import MinMaxScaler
from tabulate import tabulate

from utils.logger import get_logger

# ── 기본 가중치 ────────────────────────────────────────────────────────────────
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "coverage":           0.15,
    "accuracy":           0.20,
    "api_richness":       0.15,
    "real_time_data":     0.20,
    "route_optimization": 0.15,
    "cost_efficiency":    0.10,
    "developer_support":  0.05,
}

# ── use_case별 가중치 프리셋 ────────────────────────────────────────────────────
_CONTEXT_WEIGHTS: Dict[str, Dict[str, float]] = {
    "navigation": {
        "route_optimization": 0.30,
        "real_time_data":     0.25,
        "accuracy":           0.20,
        "coverage":           0.10,
        "api_richness":       0.08,
        "cost_efficiency":    0.05,
        "developer_support":  0.02,
    },
    "poi_search": {
        "api_richness":       0.25,
        "coverage":           0.25,
        "accuracy":           0.20,
        "real_time_data":     0.15,
        "route_optimization": 0.08,
        "cost_efficiency":    0.05,
        "developer_support":  0.02,
    },
    "traffic_analysis": {
        "real_time_data":     0.35,
        "accuracy":           0.25,
        "api_richness":       0.15,
        "route_optimization": 0.12,
        "coverage":           0.08,
        "cost_efficiency":    0.03,
        "developer_support":  0.02,
    },
    "cost_priority": {
        "cost_efficiency":    0.35,
        "api_richness":       0.20,
        "real_time_data":     0.15,
        "accuracy":           0.15,
        "route_optimization": 0.08,
        "coverage":           0.05,
        "developer_support":  0.02,
    },
}

# 지표 한글명
_METRIC_LABELS: Dict[str, str] = {
    "coverage":           "지역커버리지",
    "accuracy":           "위치정확도",
    "api_richness":       "API기능다양성",
    "real_time_data":     "실시간데이터",
    "route_optimization": "경로최적화",
    "cost_efficiency":    "비용효율성",
    "developer_support":  "개발자지원",
}

_METRICS = list(_DEFAULT_WEIGHTS.keys())


class WeightedEvaluator:
    """가중치 기반 지도 API 비교 평가기.

    Args:
        weights: 사용자 정의 가중치 dict (None이면 기본값 사용)

    Example:
        >>> ev = WeightedEvaluator()
        >>> scores = {
        ...     '카카오': {'coverage':85,'accuracy':90,'api_richness':80,
        ...                'real_time_data':75,'route_optimization':88,
        ...                'cost_efficiency':70,'developer_support':85},
        ...     'T맵':    {'coverage':80,'accuracy':85,'api_richness':75,
        ...                'real_time_data':90,'route_optimization':82,
        ...                'cost_efficiency':80,'developer_support':70},
        ... }
        >>> df = ev.evaluate_services(scores)
        >>> '종합점수' in df.columns
        True
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self.weights: Dict[str, float] = copy.deepcopy(weights or _DEFAULT_WEIGHTS)
        self._original_weights        = copy.deepcopy(self.weights)
        self._validate_weights(self.weights)

        self._scaler  = MinMaxScaler(feature_range=(0, 1))
        self._results: Optional[pd.DataFrame] = None   # 마지막 평가 결과 캐시
        self._logger  = get_logger(self.__class__.__name__)
        self._logger.info(
            "WeightedEvaluator 초기화 | 가중치합=%.2f", sum(self.weights.values())
        )

    # =========================================================
    # 내부 유틸
    # =========================================================

    @staticmethod
    def _validate_weights(weights: Dict[str, float]) -> None:
        total = round(sum(weights.values()), 6)
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"가중치 합이 1.0이어야 합니다: {total:.4f}")
        missing = set(_METRICS) - set(weights)
        if missing:
            raise ValueError(f"누락된 평가 지표: {missing}")

    def _apply_weights(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """MinMaxScaler 정규화 후 가중치를 곱해 종합점수를 계산한다."""
        normalized = self._scaler.fit_transform(raw_df[_METRICS])
        norm_df    = pd.DataFrame(normalized, index=raw_df.index, columns=_METRICS)

        for metric in _METRICS:
            norm_df[metric] = norm_df[metric] * self.weights[metric]

        norm_df["종합점수"] = norm_df[_METRICS].sum(axis=1).round(4)
        norm_df["순위"]    = norm_df["종합점수"].rank(ascending=False).astype(int)

        # 원본 점수도 함께 보관
        for metric in _METRICS:
            norm_df[f"raw_{metric}"] = raw_df[metric].values

        return norm_df.sort_values("종합점수", ascending=False)

    # =========================================================
    # 1. 경로 결과 기반 간단 점수 계산
    # =========================================================

    def evaluate(self, results: Dict) -> Dict[str, float]:
        """경로 탐색 결과(RouteResult)로부터 간단한 종합 점수를 계산한다.

        Args:
            results: {provider: RouteResult} 형식

        Returns:
            {provider: score} — 점수가 높을수록 우수
        """
        scores: Dict[str, float] = {}
        for provider, r in results.items():
            time_score = max(0.0, 100 - r.duration_min)
            dist_score = max(0.0, 100 - r.distance_km)
            scores[provider] = round(time_score * 0.6 + dist_score * 0.4, 4)
            self._logger.debug("%s 경로 점수: %.4f", provider, scores[provider])
        return scores

    # =========================================================
    # 2. 벤치마크 점수 기반 정규화 평가
    # =========================================================

    def evaluate_services(
        self, scores_dict: Dict[str, Dict[str, float]]
    ) -> pd.DataFrame:
        """API 서비스 점수를 정규화·가중치 적용해 DataFrame으로 반환한다.

        Args:
            scores_dict: {'서비스명': {'지표명': 점수(0-100), ...}, ...}

        Returns:
            DataFrame (index: 서비스명, columns: 지표들 + '종합점수' + '순위')
        """
        if not scores_dict:
            raise ValueError("scores_dict가 비어 있습니다.")

        self._logger.info("평가 시작 | 서비스: %s", list(scores_dict.keys()))

        raw_df = pd.DataFrame(scores_dict).T[_METRICS].astype(float)
        result = self._apply_weights(raw_df)
        self._results = result

        for service in result.index:
            self._logger.debug(
                "%s 종합점수: %.4f (순위: %d)",
                service, result.loc[service, "종합점수"], result.loc[service, "순위"],
            )
        self._logger.info(
            "평가 완료 | 1위: %s (%.4f)",
            result.index[0], result["종합점수"].iloc[0],
        )
        return result

    # =========================================================
    # 2. 컨텍스트 인식 평가
    # =========================================================

    def context_aware_evaluation(
        self, use_case: str, scores_dict: Dict[str, Dict[str, float]]
    ) -> pd.DataFrame:
        """사용 시나리오에 맞게 가중치를 동적 조정한 후 평가한다.

        Args:
            use_case:    'navigation' | 'poi_search' | 'traffic_analysis' | 'cost_priority'
            scores_dict: 기본 evaluate_services와 동일 형식

        Returns:
            가중치 조정 후 평가된 DataFrame
        """
        if use_case not in _CONTEXT_WEIGHTS:
            raise ValueError(
                f"지원하지 않는 use_case: {use_case!r}. "
                f"가능한 값: {list(_CONTEXT_WEIGHTS)}"
            )

        self._logger.info("컨텍스트 평가 | use_case=%s", use_case)

        # 가중치 임시 교체
        self.weights = copy.deepcopy(_CONTEXT_WEIGHTS[use_case])
        self._logger.debug("조정 가중치: %s", self.weights)

        try:
            result = self.evaluate_services(scores_dict)
        finally:
            # 반드시 원상복구
            self.weights = copy.deepcopy(self._original_weights)
            self._logger.debug("가중치 원상복구 완료")

        return result

    # =========================================================
    # 3. 상세 평가 조회
    # =========================================================

    def get_evaluation_details(self, api_name: str) -> Dict:
        """특정 서비스의 상세 평가 결과를 반환한다.

        Returns:
            {
                '종합점수': float,
                '순위': int,
                '강점': [지표명, ...],   (가중치 점수 상위 3개)
                '약점': [지표명, ...],   (가중치 점수 하위 2개)
                '지표별_점수': {지표명: 원본점수},
                '지표별_가중점수': {지표명: 가중치*정규화점수},
            }
        """
        if self._results is None:
            raise RuntimeError("evaluate_services()를 먼저 실행해야 합니다.")
        if api_name not in self._results.index:
            raise KeyError(f"'{api_name}'은 평가 결과에 없습니다. "
                           f"가능한 서비스: {list(self._results.index)}")

        row     = self._results.loc[api_name]
        weighted = {m: round(float(row[m]), 4) for m in _METRICS}
        raw      = {m: round(float(row[f"raw_{m}"]), 2) for m in _METRICS}

        sorted_metrics = sorted(weighted, key=weighted.get, reverse=True)
        strengths = [_METRIC_LABELS[m] for m in sorted_metrics[:3]]
        weaknesses = [_METRIC_LABELS[m] for m in sorted_metrics[-2:]]

        return {
            "종합점수":       round(float(row["종합점수"]), 4),
            "순위":           int(row["순위"]),
            "강점":           strengths,
            "약점":           weaknesses,
            "지표별_점수":     raw,
            "지표별_가중점수": weighted,
        }

    # =========================================================
    # 4. 결과 내보내기
    # =========================================================

    def export_results(self, format: str = "json") -> str:
        """평가 결과를 JSON / CSV / table 형식의 문자열로 내보낸다.

        Args:
            format: 'json' | 'csv' | 'table'

        Returns:
            직렬화된 문자열

        Raises:
            RuntimeError: evaluate_services() 미실행 시
            ValueError:   미지원 format
        """
        if self._results is None:
            raise RuntimeError("evaluate_services()를 먼저 실행해야 합니다.")

        export_cols = _METRICS + ["종합점수", "순위"]
        df = self._results[export_cols].copy()
        df.index.name = "서비스"

        if format == "json":
            payload = {
                "evaluation": df.reset_index().to_dict(orient="records"),
                "weights":    self._original_weights,
                "metrics":    _METRIC_LABELS,
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        if format == "csv":
            return df.to_csv(encoding="utf-8")

        if format == "table":
            display = df.copy()
            display.columns = [_METRIC_LABELS.get(c, c) for c in display.columns]
            return tabulate(display, headers="keys", tablefmt="rounded_outline",
                            floatfmt=".4f")

        raise ValueError(f"미지원 format: {format!r}. 'json', 'csv', 'table' 중 선택.")

    # =========================================================
    # 5. 콘솔 리포트 출력
    # =========================================================

    def print_evaluation_report(self) -> None:
        """평가 결과를 색상 테이블과 상세 정보로 콘솔에 출력한다."""
        if self._results is None:
            print(f"{Fore.RED}평가 결과가 없습니다. evaluate_services()를 먼저 실행하세요.{Style.RESET_ALL}")
            return

        W = 64
        def rule(c: str = "-") -> None:
            print(Fore.CYAN + c * W + Style.RESET_ALL)

        rule("=")
        print(Fore.CYAN + Style.BRIGHT + " 가중치 기반 API 평가 리포트".center(W) + Style.RESET_ALL)
        rule("=")

        # ── 종합 순위 테이블 ─────────────────────────────────────
        display_cols = ["종합점수", "순위"] + _METRICS
        df_display   = self._results[display_cols].copy()
        df_display.columns = ["종합점수", "순위"] + [_METRIC_LABELS[m] for m in _METRICS]
        print(tabulate(df_display, headers="keys", tablefmt="rounded_outline",
                       floatfmt=".4f"))
        rule()

        # ── 가중치 현황 ───────────────────────────────────────────
        print(Fore.CYAN + " 적용 가중치" + Style.RESET_ALL)
        w_rows = [[_METRIC_LABELS[m], f"{w:.0%}"] for m, w in self._original_weights.items()]
        print(tabulate(w_rows, headers=["지표", "가중치"], tablefmt="simple"))
        rule()

        # ── 서비스별 강점/약점 ────────────────────────────────────
        print(Fore.CYAN + " 서비스별 강점 / 약점" + Style.RESET_ALL)
        for rank_idx, service in enumerate(self._results.index, start=1):
            detail = self.get_evaluation_details(service)
            medal  = ["🥇", "🥈", "🥉"].pop(0) if rank_idx <= 3 else f"{rank_idx}위"
            color  = Fore.GREEN if rank_idx == 1 else Fore.YELLOW if rank_idx == 2 else Fore.WHITE
            print(
                f"  {color}{medal} {service}{Style.RESET_ALL} "
                f"(종합: {detail['종합점수']:.4f})"
            )
            print(f"    강점: {Fore.GREEN}{', '.join(detail['강점'])}{Style.RESET_ALL}")
            print(f"    약점: {Fore.RED}{', '.join(detail['약점'])}{Style.RESET_ALL}")
        rule("=")
