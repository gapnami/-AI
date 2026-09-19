import unittest
from unittest.mock import patch, MagicMock
from services.route_setup import RouteSetup

ORIGIN = {"lat": 37.5665, "lon": 126.9780}
DESTINATION = {"lat": 37.4979, "lon": 127.0276}


class TestRouteSetup(unittest.TestCase):
    @patch("services.route_setup.TMapAPIHandler")
    @patch("services.route_setup.KakaoAPIHandler")
    def test_fetch_both(self, MockKakao, MockTMap):
        MockKakao.return_value.get_route.return_value = {
            "routes": [{"summary": {"distance": 10000, "duration": 1200, "fare": {"toll": 0, "taxi": 5000}}}]
        }
        MockTMap.return_value.get_route.return_value = {
            "features": [{"properties": {"totalDistance": 9500, "totalTime": 1100, "totalFare": 0}}]
        }
        setup = RouteSetup()
        results = setup.fetch_both(ORIGIN, DESTINATION)
        self.assertIn("kakao", results)
        self.assertIn("tmap", results)


if __name__ == "__main__":
    unittest.main()
