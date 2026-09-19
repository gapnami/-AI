import unittest
from models.route_model import RouteResult
from services.api_analysis import APIAnalysis
from analysis.weighted_evaluator import WeightedEvaluator

RESULTS = {
    "kakao": RouteResult(provider="kakao", distance_m=10000, duration_s=1200, toll_fee=500),
    "tmap": RouteResult(provider="tmap", distance_m=9500, duration_s=1100, toll_fee=0),
}


class TestAPIAnalysis(unittest.TestCase):
    def test_compare(self):
        analysis = APIAnalysis()
        result = analysis.compare(RESULTS)
        self.assertIn(result.recommendation, ["kakao", "tmap"])
        self.assertEqual(len(result.scores), 2)


class TestWeightedEvaluator(unittest.TestCase):
    def test_evaluate(self):
        evaluator = WeightedEvaluator()
        scores = evaluator.evaluate(RESULTS)
        self.assertIn("kakao", scores)
        self.assertIn("tmap", scores)


if __name__ == "__main__":
    unittest.main()
