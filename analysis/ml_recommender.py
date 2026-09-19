from models.route_model import RouteResult


class MLRecommender:
    """간단한 룰 기반 추천 (향후 ML 모델로 교체 가능)."""

    def recommend(self, results: dict[str, RouteResult], preference: str = "time") -> str:
        if not results:
            return "N/A"

        if preference == "time":
            return min(results, key=lambda p: results[p].duration_s)
        elif preference == "distance":
            return min(results, key=lambda p: results[p].distance_m)
        elif preference == "cost":
            return min(results, key=lambda p: results[p].toll_fee)
        else:
            scores = {p: r.duration_s * 0.5 + r.distance_m * 0.3 + r.toll_fee * 0.2
                      for p, r in results.items()}
            return min(scores, key=scores.get)
