from services.route_setup import RouteSetup
from services.api_analysis import APIAnalysis
from services.report_generator import ReportGenerator
from analysis.weighted_evaluator import WeightedEvaluator
from analysis.ahp_analyzer import AHPAnalyzer
from analysis.ml_recommender import MLRecommender
from utils.logger import get_logger

logger = get_logger(__name__)

ORIGIN      = {"lat": 37.5665, "lon": 126.9780, "name": "서울시청"}
DESTINATION = {"lat": 37.4979, "lon": 127.0276, "name": "강남역"}

# 카카오 vs T맵 벤치마크 점수 (0-100)
_BENCHMARK_SCORES = {
    "kakao": {
        "coverage": 85, "accuracy": 90, "api_richness": 80,
        "real_time_data": 75, "route_optimization": 88,
        "cost_efficiency": 70, "developer_support": 85,
    },
    "tmap": {
        "coverage": 80, "accuracy": 85, "api_richness": 75,
        "real_time_data": 90, "route_optimization": 82,
        "cost_efficiency": 80, "developer_support": 70,
    },
}

# AHP 기준별 쌍대 비교 (>1: 카카오 우세, <1: T맵 우세)
_AHP_COMPARISONS = {
    "coverage":           {"kakao_vs_tmap": 1.2},
    "accuracy":           {"kakao_vs_tmap": 1.5},
    "real_time_data":     {"kakao_vs_tmap": 0.7},
    "route_optimization": {"kakao_vs_tmap": 1.3},
}


def main():
    logger.info("=== Map Service Analyzer 시작 ===")

    route_setup = RouteSetup()
    results = route_setup.fetch_both(ORIGIN, DESTINATION)

    if not results:
        logger.error("API 응답 없음. API 키를 확인하세요.")
        return

    analysis = APIAnalysis()
    result = analysis.compare(results)

    evaluator = WeightedEvaluator()
    weighted_scores = evaluator.evaluate_services(_BENCHMARK_SCORES)
    logger.info(f"가중치 평가 1위: {weighted_scores.index[0]}")

    ahp = AHPAnalyzer()
    ahp_scores = ahp.rank_services(
        criteria=list(_AHP_COMPARISONS.keys()),
        pairwise_comparisons=_AHP_COMPARISONS,
    )
    logger.info(f"AHP 평가 순위: {ahp_scores['ranking']}")

    recommender = MLRecommender()
    recommendation = recommender.recommend(results, preference="time")
    logger.info(f"추천 서비스: {recommendation}")

    reporter = ReportGenerator()
    report_path = reporter.generate(result)
    logger.info(f"리포트 저장 완료: {report_path}")
    logger.info("=== 분석 완료 ===")


if __name__ == "__main__":
    main()
