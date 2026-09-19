"""
API 핸들러 단위 테스트.

대상:
  - KakaoAPIHandler (core/kakao_api_handler.py)
  - TmapAPIHandler  (core/tmap_api_handler.py)

실행:
  python -m pytest tests/test_api_handlers.py -v
  python -m unittest tests.test_api_handlers -v
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import requests

from core.kakao_api_handler import KakaoAPIHandler
from core.tmap_api_handler import TmapAPIHandler

# ── 공통 픽스처 ───────────────────────────────────────────────────────────────
TEST_KEY_KAKAO = "test_kakao_key_1234567890abcdef"
TEST_KEY_TMAP  = "test_tmap_key_abcdefghijklmnop"

START  = (37.5665, 126.9780)   # 서울시청
END    = (37.4979, 127.0276)   # 강남역


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """requests.Response Mock을 생성한다."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None   # 기본은 성공
    mock.text = str(json_data)
    return mock


def _make_error_response(status_code: int, message: str = "Error") -> MagicMock:
    """HTTP 오류 응답 Mock을 생성한다."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = message
    http_err = requests.exceptions.HTTPError(response=mock)
    mock.raise_for_status.side_effect = http_err
    return mock


# ══════════════════════════════════════════════════════════════════════════════
# 카카오맵 API 핸들러 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestKakaoAPIHandlerInit(unittest.TestCase):
    """KakaoAPIHandler 초기화 테스트."""

    def test_init_sets_headers(self):
        """API 키가 Authorization 헤더에 올바르게 설정된다."""
        handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.assertIn("Authorization", handler.headers)
        self.assertEqual(handler.headers["Authorization"], f"KakaoAK {TEST_KEY_KAKAO}")

    def test_init_sets_base_url(self):
        """base_url이 카카오 로컬 API 주소로 설정된다."""
        handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.assertIn("dapi.kakao.com", handler.base_url)

    def test_init_sets_timeout(self):
        """timeout이 양수로 설정된다."""
        handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.assertGreater(handler.timeout, 0)

    def test_init_empty_key_raises(self):
        """빈 API 키로 초기화하면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            KakaoAPIHandler("")


class TestKakaoSearchPlace(unittest.TestCase):
    """KakaoAPIHandler.search_place() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.mock_data = {
            "documents": [
                {
                    "id": "1234",
                    "place_name": "강남역",
                    "category_name": "지하철역",
                    "address_name": "서울 강남구 역삼동",
                    "road_address_name": "서울 강남구 강남대로 396",
                    "x": "127.0276",
                    "y": "37.4979",
                    "phone": "02-1234-5678",
                    "place_url": "http://place.map.kakao.com/1234",
                    "distance": "0",
                }
            ],
            "meta": {"total_count": 1, "pageable_count": 1, "is_end": True},
        }

    @patch("core.kakao_api_handler.requests.request")
    def test_search_place_success(self, mock_req):
        """정상 키워드 검색 시 documents를 포함한 dict를 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_place("강남역")
        self.assertIn("documents", result)
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(result["documents"][0]["place_name"], "강남역")

    @patch("core.kakao_api_handler.requests.request")
    def test_search_place_pagination(self, mock_req):
        """page, size 파라미터가 요청에 포함된다."""
        mock_req.return_value = _make_response(self.mock_data)
        self.handler.search_place("카페", page=2, size=5)
        _, kwargs = mock_req.call_args
        params = kwargs.get("params", {})
        self.assertEqual(params["page"], 2)
        self.assertEqual(params["size"], 5)

    def test_search_place_empty_query_raises(self):
        """빈 문자열 검색 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.search_place("")

    def test_search_place_invalid_page_raises(self):
        """page가 범위를 벗어나면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.search_place("카페", page=0)
        with self.assertRaises(ValueError):
            self.handler.search_place("카페", page=46)

    def test_search_place_invalid_size_raises(self):
        """size가 범위를 벗어나면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.search_place("카페", size=0)
        with self.assertRaises(ValueError):
            self.handler.search_place("카페", size=16)


class TestKakaoGetCoordsFromAddress(unittest.TestCase):
    """KakaoAPIHandler.get_coords_from_address() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.mock_data = {
            "documents": [{"x": "127.0276", "y": "37.4979", "address_name": "서울 강남구 역삼동"}],
            "meta": {"total_count": 1},
        }

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_lat_lon_tuple(self, mock_req):
        """정상 주소 변환 시 (위도, 경도) 튜플을 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        # lru_cache 초기화
        self.handler.get_coords_from_address.cache_clear()
        result = self.handler.get_coords_from_address("서울 강남구 역삼동")
        self.assertIsNotNone(result)
        lat, lon = result
        self.assertAlmostEqual(lat, 37.4979, places=3)
        self.assertAlmostEqual(lon, 127.0276, places=3)

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_none_for_no_result(self, mock_req):
        """검색 결과가 없으면 None을 반환한다."""
        mock_req.return_value = _make_response({"documents": [], "meta": {"total_count": 0}})
        self.handler.get_coords_from_address.cache_clear()
        result = self.handler.get_coords_from_address("존재하지않는주소xyz")
        self.assertIsNone(result)

    @patch("core.kakao_api_handler.requests.request")
    def test_lru_cache_hit(self, mock_req):
        """동일 주소 반복 호출 시 캐시가 사용된다 (API 1회만 호출)."""
        mock_req.return_value = _make_response(self.mock_data)
        self.handler.get_coords_from_address.cache_clear()
        self.handler.get_coords_from_address("서울 강남구 역삼동")
        self.handler.get_coords_from_address("서울 강남구 역삼동")
        self.assertEqual(mock_req.call_count, 1)

    def test_empty_address_raises(self):
        """빈 주소 문자열 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_coords_from_address("  ")


class TestKakaoGetReverseCoords(unittest.TestCase):
    """KakaoAPIHandler.get_reverse_coords() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_road_address(self, mock_req):
        """도로명 주소가 있을 때 도로명을 반환한다."""
        mock_req.return_value = _make_response({
            "documents": [{
                "road_address": {"address_name": "서울 강남구 강남대로 396"},
                "address":      {"address_name": "서울 강남구 역삼동"},
            }]
        })
        result = self.handler.get_reverse_coords(37.4979, 127.0276)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_none_for_no_result(self, mock_req):
        """결과가 없으면 None을 반환한다."""
        mock_req.return_value = _make_response({"documents": []})
        result = self.handler.get_reverse_coords(0.0, 0.0)
        self.assertIsNone(result)

    def test_invalid_latitude_raises(self):
        """위도 범위 초과 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_reverse_coords(91.0, 127.0)

    def test_invalid_longitude_raises(self):
        """경도 범위 초과 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_reverse_coords(37.5, 181.0)


class TestKakaoGetRoute(unittest.TestCase):
    """KakaoAPIHandler.get_route() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.mock_data = {
            "routes": [{
                "result_code": 0,
                "result_msg":  "길찾기 성공",
                "summary": {
                    "distance": 11764,
                    "duration": 2373,
                    "fare":     {"toll": 0, "taxi": 9800},
                },
                "sections": [],
            }]
        }

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_distance_and_duration(self, mock_req):
        """정상 응답 시 distance와 duration을 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_route(START, END)
        self.assertEqual(result["distance"], 11764)
        self.assertEqual(result["duration"], 2373)

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_result_code(self, mock_req):
        """응답에 result_code가 포함된다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_route(START, END)
        self.assertIn("result_code", result)
        self.assertEqual(result["result_code"], 0)

    @patch("core.kakao_api_handler.requests.request")
    def test_empty_routes_returns_zero(self, mock_req):
        """routes가 빈 경우 distance=0, duration=0을 반환한다."""
        mock_req.return_value = _make_response({"routes": []})
        result = self.handler.get_route(START, END)
        self.assertEqual(result["distance"], 0)
        self.assertEqual(result["duration"], 0)

    def test_invalid_vehicle_type_raises(self):
        """지원하지 않는 vehicle_type 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_route(START, END, vehicle_type="helicopter")

    def test_invalid_start_coords_raises(self):
        """잘못된 출발 좌표 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_route((200.0, 127.0), END)

    def test_invalid_end_coords_raises(self):
        """잘못된 목적 좌표 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_route(START, (37.5, 200.0))


class TestKakaoGetTrafficInfo(unittest.TestCase):
    """KakaoAPIHandler.get_traffic_info() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.mock_data = {
            "documents": [
                {"place_name": "시청역", "category_group_code": "SW8", "distance": "120"},
                {"place_name": "을지로입구역", "category_group_code": "SW8", "distance": "350"},
                {"place_name": "광화문역", "category_group_code": "SW8", "distance": "480"},
            ],
            "meta": {"total_count": 3},
        }

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_congestion_key(self, mock_req):
        """응답에 congestion 키가 포함된다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_traffic_info(37.5665, 126.9780)
        self.assertIn("congestion", result)

    @patch("core.kakao_api_handler.requests.request")
    def test_high_congestion_when_many_stations(self, mock_req):
        """지하철역 3개 이상 → high 반환."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_traffic_info(37.5665, 126.9780)
        self.assertEqual(result["congestion"], "high")

    @patch("core.kakao_api_handler.requests.request")
    def test_low_congestion_when_no_stations(self, mock_req):
        """지하철역 0개 → low 반환."""
        mock_req.return_value = _make_response({"documents": [], "meta": {"total_count": 0}})
        result = self.handler.get_traffic_info(37.5665, 126.9780)
        self.assertEqual(result["congestion"], "low")

    def test_invalid_radius_raises(self):
        """radius가 범위를 벗어나면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_traffic_info(37.5, 126.9, radius=0)
        with self.assertRaises(ValueError):
            self.handler.get_traffic_info(37.5, 126.9, radius=25000)


class TestKakaoSearchNearbyPoi(unittest.TestCase):
    """KakaoAPIHandler.search_nearby_poi() 테스트."""

    def setUp(self):
        self.handler = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.mock_data = {
            "documents": [
                {
                    "place_name": "스타벅스 시청점",
                    "category_group_code": "CE7",
                    "road_address_name": "서울 중구 세종대로 110",
                    "address_name": "서울 중구 태평로1가 25",
                    "x": "126.9770", "y": "37.5660",
                    "distance": "52",
                    "phone": "02-1111-2222",
                    "place_url": "http://place.map.kakao.com/9999",
                    "category_name": "음식점 > 카페",
                },
            ],
            "meta": {"total_count": 1},
        }

    @patch("core.kakao_api_handler.requests.request")
    def test_returns_normalized_list(self, mock_req):
        """정규화된 POI 리스트를 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_nearby_poi(37.5665, 126.9780, "CE7", 300)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        poi = result[0]
        for key in ("name", "address", "x", "y", "distance", "phone", "url", "category"):
            self.assertIn(key, poi)

    @patch("core.kakao_api_handler.requests.request")
    def test_distance_is_int(self, mock_req):
        """POI distance 값이 정수다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_nearby_poi(37.5665, 126.9780)
        self.assertIsInstance(result[0]["distance"], int)

    @patch("core.kakao_api_handler.requests.request")
    def test_empty_result_returns_empty_list(self, mock_req):
        """결과가 없으면 빈 리스트를 반환한다."""
        mock_req.return_value = _make_response({"documents": [], "meta": {"total_count": 0}})
        result = self.handler.search_nearby_poi(37.5665, 126.9780)
        self.assertEqual(result, [])


class TestKakaoCalculateDistance(unittest.TestCase):
    """KakaoAPIHandler.calculate_distance() 테스트."""

    def test_same_point_is_zero(self):
        """동일 좌표 간 거리는 0이다."""
        dist = KakaoAPIHandler.calculate_distance(37.5665, 126.9780, 37.5665, 126.9780)
        self.assertAlmostEqual(dist, 0.0, places=3)

    def test_known_distance(self):
        """서울시청↔강남역 거리는 약 7~10km 범위에 있다."""
        dist = KakaoAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
        self.assertGreater(dist, 7_000)
        self.assertLess(dist, 10_000)

    def test_symmetry(self):
        """A→B 거리와 B→A 거리는 동일하다."""
        d1 = KakaoAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
        d2 = KakaoAPIHandler.calculate_distance(37.4979, 127.0276, 37.5665, 126.9780)
        self.assertAlmostEqual(d1, d2, places=3)

    def test_returns_float(self):
        """반환값이 float이다."""
        dist = KakaoAPIHandler.calculate_distance(37.5, 126.9, 37.6, 127.0)
        self.assertIsInstance(dist, float)


# ══════════════════════════════════════════════════════════════════════════════
# T맵 API 핸들러 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestTmapAPIHandlerInit(unittest.TestCase):
    """TmapAPIHandler 초기화 테스트."""

    def test_init_sets_app_key_header(self):
        """appKey가 헤더에 올바르게 설정된다."""
        handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.assertEqual(handler.headers["appKey"], TEST_KEY_TMAP)

    def test_init_sets_base_url(self):
        """base_url이 T맵 API 주소로 설정된다."""
        handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.assertIn("openapi.sk.com/tmap", handler.base_url)

    def test_init_sets_timeout(self):
        """timeout이 양수로 설정된다."""
        handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.assertGreater(handler.timeout, 0)

    def test_init_empty_key_raises(self):
        """빈 App Key로 초기화하면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            TmapAPIHandler("")


class TestTmapSearchPlace(unittest.TestCase):
    """TmapAPIHandler.search_place() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.mock_data = {
            "searchPoiInfo": {
                "pois": {
                    "poi": [
                        {
                            "name": "강남역[2호선]",
                            "noorLat": "37.49808633653005",
                            "noorLon": "127.02800140627488",
                            "upperAddrName": "서울특별시",
                            "middleAddrName": "강남구",
                            "lowerAddrName": "역삼동",
                            "telNo": "02-1234-5678",
                            "mlClass": "지하철역",
                        }
                    ]
                }
            }
        }

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_count_and_documents(self, mock_req):
        """정상 응답 시 count와 documents를 포함한 dict를 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_place("강남역")
        self.assertIn("count", result)
        self.assertIn("documents", result)
        self.assertEqual(result["count"], 1)

    @patch("core.tmap_api_handler.requests.request")
    def test_documents_have_required_keys(self, mock_req):
        """각 document에 name, address, lat, lon 키가 존재한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_place("강남역")
        doc = result["documents"][0]
        for key in ("name", "address", "lat", "lon"):
            self.assertIn(key, doc)

    def test_empty_query_raises(self):
        """빈 검색어 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.search_place("   ")


class TestTmapGetCoordsFromAddress(unittest.TestCase):
    """TmapAPIHandler.get_coords_from_address() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.mock_data = {
            "coordinateInfo": {
                "coordinate": [{"lat": "37.5012767241426", "lon": "127.039600248343"}]
            }
        }

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_lat_lon_tuple(self, mock_req):
        """정상 응답 시 (위도, 경도) 튜플을 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        self.handler.get_coords_from_address.cache_clear()
        result = self.handler.get_coords_from_address("서울 강남구 테헤란로 212")
        self.assertIsNotNone(result)
        lat, lon = result
        self.assertIsInstance(lat, float)
        self.assertIsInstance(lon, float)

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_none_for_empty_coordinate(self, mock_req):
        """좌표 결과가 없으면 None을 반환한다."""
        mock_req.return_value = _make_response({"coordinateInfo": {"coordinate": []}})
        self.handler.get_coords_from_address.cache_clear()
        result = self.handler.get_coords_from_address("없는주소xyz")
        self.assertIsNone(result)

    @patch("core.tmap_api_handler.requests.request")
    def test_lru_cache_hit(self, mock_req):
        """동일 주소 반복 호출 시 API가 1회만 호출된다."""
        mock_req.return_value = _make_response(self.mock_data)
        self.handler.get_coords_from_address.cache_clear()
        self.handler.get_coords_from_address("서울 강남구 테헤란로 212")
        self.handler.get_coords_from_address("서울 강남구 테헤란로 212")
        self.assertEqual(mock_req.call_count, 1)

    def test_empty_address_raises(self):
        """빈 주소 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_coords_from_address("")


class TestTmapGetRoute(unittest.TestCase):
    """TmapAPIHandler.get_route() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.mock_data = {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [126.9780, 37.5665]},
                    "properties": {
                        "totalDistance": 10601,
                        "totalTime":     8468,
                        "totalFare":     0,
                        "index":         0,
                    },
                }
            ]
        }

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_distance_and_duration(self, mock_req):
        """정상 응답 시 distance와 duration을 반환한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_route(START, END, vehicle_type="walk")
        self.assertEqual(result["distance"], 10601)
        self.assertEqual(result["duration"], 8468)

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_fare_key(self, mock_req):
        """응답에 fare 키가 포함된다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.get_route(START, END)
        self.assertIn("fare", result)

    @patch("core.tmap_api_handler.requests.request")
    def test_car_route_includes_traffic(self, mock_req):
        """자동차 경로 요청 시 trafficInfo=Y가 payload에 포함된다."""
        mock_req.return_value = _make_response(self.mock_data)
        self.handler.get_route(START, END, vehicle_type="car")
        _, kwargs = mock_req.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("trafficInfo"), "Y")

    def test_invalid_vehicle_type_raises(self):
        """지원하지 않는 vehicle_type 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_route(START, END, vehicle_type="jet")

    def test_invalid_start_coords_raises(self):
        """잘못된 출발 좌표 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_route((-100.0, 127.0), END)


class TestTmapGetTrafficInfo(unittest.TestCase):
    """TmapAPIHandler.get_traffic_info() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_congestion_key(self, mock_req):
        """응답에 congestion 키가 포함된다."""
        mock_req.return_value = _make_response({
            "searchPoiInfo": {"pois": {"poi": [
                {"name": "서울역", "noorLat": "37.5545", "noorLon": "126.9707",
                 "upperAddrName": "서울특별시", "middleAddrName": "용산구",
                 "lowerAddrName": "", "telNo": "", "mlClass": "지하철역"},
            ]}}
        })
        result = self.handler.get_traffic_info(37.5665, 126.9780, radius=2000)
        self.assertIn("congestion", result)
        self.assertIn(result["congestion"], ("low", "medium", "high", "unknown"))

    @patch("core.tmap_api_handler.requests.request")
    def test_unknown_on_api_error(self, mock_req):
        """API 오류 시 congestion=unknown을 반환한다."""
        mock_req.side_effect = requests.exceptions.HTTPError(
            response=_make_error_response(400)
        )
        result = self.handler.get_traffic_info(37.5665, 126.9780)
        self.assertEqual(result["congestion"], "unknown")

    def test_invalid_coords_raises(self):
        """잘못된 좌표 시 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_traffic_info(200.0, 127.0)


class TestTmapSearchNearbyPoi(unittest.TestCase):
    """TmapAPIHandler.search_nearby_poi() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.mock_data = {
            "searchPoiInfo": {
                "pois": {
                    "poi": [
                        {
                            "name": "스타벅스 무교동점",
                            "noorLat": "37.5671",
                            "noorLon": "126.9765",
                            "upperAddrName": "서울특별시",
                            "middleAddrName": "중구",
                            "lowerAddrName": "무교동",
                            "telNo": "02-9999-8888",
                            "mlClass": "카페",
                        }
                    ]
                }
            }
        }

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_list(self, mock_req):
        """반환 타입이 list다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_nearby_poi(37.5665, 126.9780, "cafe", 1000)
        self.assertIsInstance(result, list)

    @patch("core.tmap_api_handler.requests.request")
    def test_poi_has_required_keys(self, mock_req):
        """각 POI에 name, lat, lon, distance 키가 존재한다."""
        mock_req.return_value = _make_response(self.mock_data)
        result = self.handler.search_nearby_poi(37.5665, 126.9780, "cafe", 5000)
        if result:
            poi = result[0]
            for key in ("name", "address", "lat", "lon", "distance", "tel", "category"):
                self.assertIn(key, poi)

    @patch("core.tmap_api_handler.requests.request")
    def test_sorted_by_distance(self, mock_req):
        """결과가 거리순으로 정렬된다."""
        mock_data_multi = {
            "searchPoiInfo": {"pois": {"poi": [
                {"name": "B", "noorLat": "37.5760", "noorLon": "126.9770",
                 "upperAddrName": "", "middleAddrName": "", "lowerAddrName": "",
                 "telNo": "", "mlClass": ""},
                {"name": "A", "noorLat": "37.5670", "noorLon": "126.9785",
                 "upperAddrName": "", "middleAddrName": "", "lowerAddrName": "",
                 "telNo": "", "mlClass": ""},
            ]}}
        }
        mock_req.return_value = _make_response(mock_data_multi)
        result = self.handler.search_nearby_poi(37.5665, 126.9780, "cafe", 20000)
        if len(result) >= 2:
            self.assertLessEqual(result[0]["distance"], result[1]["distance"])


class TestTmapGetTollInfo(unittest.TestCase):
    """TmapAPIHandler.get_toll_info() 테스트."""

    def setUp(self):
        self.handler = TmapAPIHandler(TEST_KEY_TMAP)
        self.route_mock = {
            "features": [
                {
                    "properties": {
                        "totalDistance": 11870,
                        "totalTime":     2800,
                        "totalFare":     1500,
                        "facilityType":  "3",
                        "tollFare":      1500,
                    }
                }
            ]
        }

    @patch("core.tmap_api_handler.requests.request")
    def test_returns_toll_fare(self, mock_req):
        """toll_fare 키를 포함한 dict를 반환한다."""
        mock_req.return_value = _make_response(self.route_mock)
        result = self.handler.get_toll_info([START, END])
        self.assertIn("toll_fare", result)
        self.assertIn("total_fare", result)
        self.assertIn("distance_m", result)
        self.assertIn("duration_s", result)

    def test_too_few_coords_raises(self):
        """좌표가 1개 이하이면 ValueError가 발생한다."""
        with self.assertRaises(ValueError):
            self.handler.get_toll_info([START])


class TestTmapCalculateDistance(unittest.TestCase):
    """TmapAPIHandler.calculate_distance() 테스트."""

    def test_same_point_is_zero(self):
        """동일 좌표 간 거리는 0이다."""
        dist = TmapAPIHandler.calculate_distance(37.5665, 126.9780, 37.5665, 126.9780)
        self.assertAlmostEqual(dist, 0.0, places=3)

    def test_known_distance(self):
        """서울시청↔강남역 거리는 약 7~10km 범위에 있다."""
        dist = TmapAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
        self.assertGreater(dist, 7_000)
        self.assertLess(dist, 10_000)

    def test_matches_kakao_haversine(self):
        """T맵과 카카오의 Haversine 결과가 동일하다."""
        d_kakao = KakaoAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
        d_tmap  = TmapAPIHandler.calculate_distance(37.5665, 126.9780, 37.4979, 127.0276)
        self.assertAlmostEqual(d_kakao, d_tmap, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# 에러 처리 공통 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling(unittest.TestCase):
    """에러 처리 통합 테스트."""

    def setUp(self):
        self.kakao = KakaoAPIHandler(TEST_KEY_KAKAO)
        self.tmap  = TmapAPIHandler(TEST_KEY_TMAP)

    def test_invalid_api_key_kakao(self):
        """빈 API 키로 카카오 핸들러 생성 시 ValueError."""
        with self.assertRaises(ValueError):
            KakaoAPIHandler("")

    def test_invalid_api_key_tmap(self):
        """빈 API 키로 T맵 핸들러 생성 시 ValueError."""
        with self.assertRaises(ValueError):
            TmapAPIHandler("")

    @patch("core.kakao_api_handler.requests.request")
    def test_network_timeout_kakao(self, mock_req):
        """네트워크 타임아웃 시 RequestException 계열이 발생한다."""
        mock_req.side_effect = requests.exceptions.ReadTimeout("timeout")
        with self.assertRaises(Exception):
            self.kakao.search_place("강남역")

    @patch("core.tmap_api_handler.requests.request")
    def test_network_timeout_tmap(self, mock_req):
        """T맵 네트워크 타임아웃 시 예외가 발생한다."""
        mock_req.side_effect = requests.exceptions.ReadTimeout("timeout")
        with self.assertRaises(Exception):
            self.tmap.search_place("강남역")

    def test_invalid_coordinates_kakao_get_route(self):
        """카카오 경로 탐색 시 잘못된 좌표 → ValueError."""
        with self.assertRaises(ValueError):
            self.kakao.get_route((999.0, 127.0), (37.5, 127.0))

    def test_invalid_coordinates_tmap_get_route(self):
        """T맵 경로 탐색 시 잘못된 좌표 → ValueError."""
        with self.assertRaises(ValueError):
            self.tmap.get_route((37.5, -999.0), (37.5, 127.0))

    @patch("core.kakao_api_handler.requests.request")
    def test_empty_search_result_kakao(self, mock_req):
        """카카오 검색 결과 없을 때 빈 documents를 반환한다."""
        mock_req.return_value = _make_response(
            {"documents": [], "meta": {"total_count": 0, "is_end": True}}
        )
        result = self.kakao.search_place("존재하지않는장소zzz")
        self.assertEqual(result["documents"], [])

    @patch("core.tmap_api_handler.requests.request")
    def test_empty_search_result_tmap(self, mock_req):
        """T맵 검색 결과 없을 때 count=0을 반환한다."""
        mock_req.return_value = _make_response(
            {"searchPoiInfo": {"pois": {"poi": []}}}
        )
        result = self.tmap.search_place("존재하지않는장소zzz")
        self.assertEqual(result["count"], 0)

    @patch("core.kakao_api_handler.requests.request")
    def test_http_403_kakao_raises(self, mock_req):
        """카카오 403 응답 시 HTTPError가 발생한다."""
        mock_req.return_value = _make_error_response(403, "Forbidden")
        with self.assertRaises(requests.exceptions.HTTPError):
            self.kakao.search_place("강남역")

    @patch("core.tmap_api_handler.requests.request")
    def test_http_403_tmap_raises(self, mock_req):
        """T맵 403 응답 시 HTTPError가 발생한다."""
        mock_req.return_value = _make_error_response(403, "INVALID_API_KEY")
        with self.assertRaises(requests.exceptions.HTTPError):
            self.tmap.search_place("강남역")


# ══════════════════════════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
