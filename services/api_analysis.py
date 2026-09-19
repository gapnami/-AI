from models.route_model import RouteResult
from models.analysis_result import AnalysisResult
from utils.logger import get_logger

logger = get_logger(__name__)


class APIAnalysis:
    def compare(self, results: dict[str, RouteResult], route_id: str = "route_001") -> AnalysisResult:
        scores = {}
        for provider, result in results.items():
            score = self._score(result)
            scores[provider] = score
            logger.info(f"{provider} score: {score:.2f}")

        recommendation = max(scores, key=scores.get) if scores else "N/A"
        return AnalysisResult(
            route_id=route_id,
            scores=scores,
            recommendation=recommendation,
            details={p: {"distance_km": r.distance_km, "duration_min": r.duration_min}
                     for p, r in results.items()},
        )

    def _score(self, result: RouteResult) -> float:
        time_score = max(0, 100 - result.duration_min)
        dist_score = max(0, 100 - result.distance_km)
        return (time_score * 0.6 + dist_score * 0.4)
