"""
Flask 기반 지도 서비스 경로 분석 웹 서버.

실행: python server.py
접속: http://localhost:5000
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from flask import Flask, jsonify, make_response, render_template, request

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True   # 템플릿 파일 변경 시 자동 반영
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # 브라우저 정적 파일 캐시 비활성화

from config.api_config import config
from core.kakao_api_handler import KakaoAPIHandler
from services.route_setup import RouteSetup
from services.api_analysis import APIAnalysis

_kakao    = KakaoAPIHandler(config.kakao.api_key)
_setup    = RouteSetup()
_analysis = APIAnalysis()


def _weights_from_selection(selected_prefs: list) -> dict:
    """선택된 선호도 항목(1~2개)에서 가중치 딕셔너리를 계산한다.

    선택 규칙:
        1개 선택 → 해당 항목 100%, 나머지 0%
        2개 선택 → 각 50% (첫 번째 항목에 나머지 1% 귀속)
        미선택   → 균등 25%씩
    """
    all_dims = ['cheap', 'fast', 'comfort', 'safe']
    weights  = {d: 0 for d in all_dims}

    valid = [p for p in selected_prefs if p in weights]
    if not valid:
        return {d: 25 for d in all_dims}

    n    = len(valid)
    base = 100 // n
    rem  = 100 - base * n

    for i, key in enumerate(valid):
        weights[key] = base + (rem if i == 0 else 0)

    return weights


# ── 교통 수단별 편안함 품질 점수 ──────────────────────────────────────────────
# KTX/SRT: 지정 좌석·고속 이동으로 최고 편안함
# 지하철/ITX: 보통 (혼잡 가능)
# 버스: 장거리 시 불편 (입석·진동 등)
_LEG_QUALITY_SCORE = {
    "train":  25,   # KTX / SRT / ITX-새마을 등
    "subway": 8,    # 지하철 / 광역전철
    "bus":    -10,  # 시내·시외버스
    "walk":   0,    # 도보는 별도 페널티로 처리
}
_CAR_COMFORT_BASE = 58.0   # 자동차: 도어투도어이나 운전 피로 반영

# ── 교통 수단별 안전 점수 (통계 기반) ────────────────────────────────────────
# 출처 기준: 10억 승객km당 사망자 수 역산 (낮을수록 안전 → 점수 높음)
#   KTX/SRT(열차): ~0.03  → 95점 (자동차 대비 약 100배 안전)
#   지하철:        ~0.05  → 90점
#   버스:          ~0.4   → 70점 (자동차보다 안전)
#   자동차:        ~3.1   → 45점 (기준 교통수단)
_LEG_SAFETY_SCORE = {
    "train":  95,   # KTX / SRT: 국내 철도 사고율 매우 낮음
    "subway": 90,   # 지하철: 전용 선로, 충돌 위험 최소
    "bus":    70,   # 시외·시내버스: 자동차보다 통계적으로 안전
    "walk":   60,   # 도보: 상황따라 다르나 차량 충돌 위험은 낮음
}
_CAR_SAFETY_BASE = 45.0    # 자동차: 교통사고 사망률 가장 높은 수단


def _transit_safety_score(result) -> float:
    """ODsay 대중교통 결과의 안전 절대 점수 (0~100).

    통계적 사고 사망률 기반:
      · KTX/SRT (열차): 95점  — 10억km당 사망자 자동차의 1/100
      · 지하철:          90점  — 전용 선로, 충돌 위험 최소
      · 버스:            70점  — 자동차보다 통계적으로 안전
    """
    transit_legs = [l for l in (result.transit_legs or []) if l.get("type") != "walk"]
    if not transit_legs:
        return 70.0

    score = sum(
        _LEG_SAFETY_SCORE.get(l.get("type", "bus"), 70)
        for l in transit_legs
    ) / len(transit_legs)
    return round(score, 1)


def _transit_comfort_score(result) -> float:
    """ODsay 대중교통 결과의 편안함 절대 점수 (0~100).

    높을수록 편안:
      · 도보 거리가 짧을수록 ↑  (100m당 0.8점 감점, 최대 30점)
      · 환승 횟수가 적을수록 ↑  (1회당 8점 감점)
      · KTX·SRT 탑승 시 ↑      (+25)
      · 시내·시외버스 위주면 ↓  (−10 per leg)
    """
    legs    = result.transit_legs or []
    walk_m  = result.raw.get("walk_distance", 0)

    transit_legs   = [l for l in legs if l.get("type") != "walk"]
    transfer_count = max(len(transit_legs) - 1, 0)

    if transit_legs:
        quality = sum(
            _LEG_QUALITY_SCORE.get(l.get("type", "bus"), 0)
            for l in transit_legs
        ) / len(transit_legs)
    else:
        quality = 0.0

    walk_penalty     = min(walk_m / 1000 * 8, 30)   # 최대 30점 감점
    transfer_penalty = transfer_count * 8

    score = 55.0 + quality - walk_penalty - transfer_penalty
    return round(max(0.0, min(100.0, score)), 1)


def _car_highway_ratio(result) -> float:
    """자동차 경로에서 고속도로 비율(0~1)을 계산한다.

    T맵: facilityType=1 (고속도로) 구간 거리 합산
    카카오: 도로명에 '고속도로' 포함 구간 거리 합산
    """
    raw = result.raw

    if result.provider == "tmap":
        features = raw.get("features", [])
        total = highway = 0
        for feat in features:
            if feat.get("geometry", {}).get("type") == "LineString":
                props = feat.get("properties", {})
                dist  = props.get("distance", 0)
                total += dist
                if str(props.get("facilityType", "0")) == "1":
                    highway += dist
        return highway / total if total else 0.0

    if result.provider == "kakao":
        routes   = raw.get("routes", [])
        sections = routes[0].get("sections", []) if routes else []
        total = highway = 0
        for sec in sections:
            for road in sec.get("roads", []):
                dist = road.get("distance", 0)
                name = road.get("name", "")
                total += dist
                if "고속도로" in name or "고속" in name:
                    highway += dist
        return highway / total if total else 0.0

    return 0.0


def _fmt_time(minutes: float) -> str:
    m = round(minutes)
    if m < 60:
        return f"{m}분"
    h, r = divmod(m, 60)
    return f"{h}시간" if r == 0 else f"{h}시간 {r}분"


def _calc_pref_scores(results: dict, weights: dict) -> tuple:
    """선호도 가중치 기반 종합 점수 계산 (N개 서비스 지원).

    Returns:
        final_scores : {provider: weighted_total (0~100)}
        breakdown    : {provider: {dim: score (0~100)}}
        dim_meta     : {dim: {label, unit, provider: value_str, ...}}
    """
    providers = list(results.keys())
    dims = ['cheap', 'fast', 'comfort', 'safe']

    if not providers:
        return {}, {}, {}

    if len(providers) == 1:
        p = providers[0]
        return {p: 100.0}, {p: {d: 100.0 for d in dims}}, {}

    total_w = sum(weights.values()) or 1
    norm_w  = {k: v / total_w for k, v in weights.items()}

    def rel_lower(vals: list) -> list:
        """낮을수록 좋은 지표의 상대 점수 (N개 지원)."""
        total = sum(vals)
        if total == 0:
            return [round(100.0 / len(vals), 1)] * len(vals)
        inv_sum = sum(total - v for v in vals)
        if inv_sum == 0:
            return [round(100.0 / len(vals), 1)] * len(vals)
        return [round((total - v) / inv_sum * 100, 1) for v in vals]

    def rel_higher(vals: list) -> list:
        """높을수록 좋은 지표의 상대 점수 (N개 지원)."""
        total = sum(vals)
        if total == 0:
            return [round(100.0 / len(vals), 1)] * len(vals)
        return [round(v / total * 100, 1) for v in vals]

    # ── cheap: 통행료 (낮을수록 우수) ────────────────────────────
    costs = [results[p].toll_fee for p in providers]
    cheap_scores = rel_lower(costs)

    # ── fast: 소요시간 (낮을수록 우수) ───────────────────────────
    times = [results[p].duration_min for p in providers]
    fast_scores = rel_lower(times)

    # ── comfort ───────────────────────────────────────────────────
    is_transit = 'odsay' in providers
    if is_transit:
        comfort_abs = {
            p: (_transit_comfort_score(results[p]) if p == 'odsay' else _CAR_COMFORT_BASE)
            for p in providers
        }
        comfort_scores = rel_higher([comfort_abs[p] for p in providers])
        ratios = {}
    else:
        ratios = {p: _car_highway_ratio(results[p]) for p in providers}
        comfort_scores = rel_higher([ratios[p] for p in providers])

    # ── safe ──────────────────────────────────────────────────────
    if is_transit:
        safety_abs = {
            p: (_transit_safety_score(results[p]) if p == 'odsay' else _CAR_SAFETY_BASE)
            for p in providers
        }
        safe_scores = rel_higher([safety_abs[p] for p in providers])
        speeds = {}
    else:
        speeds = {
            p: results[p].distance_km * 60 / max(results[p].duration_min, 0.1)
            for p in providers
        }
        safe_scores = rel_lower([speeds[p] for p in providers])

    breakdown = {
        p: {
            'cheap':   cheap_scores[i],
            'fast':    fast_scores[i],
            'comfort': comfort_scores[i],
            'safe':    safe_scores[i],
        }
        for i, p in enumerate(providers)
    }

    # ── dim_meta ──────────────────────────────────────────────────
    if is_transit:
        def _comfort_label(p: str) -> str:
            if p == 'odsay':
                r      = results[p]
                walk_km   = r.raw.get("walk_distance", 0) / 1000
                t_legs    = [l for l in (r.transit_legs or []) if l.get("type") != "walk"]
                transfers = max(len(t_legs) - 1, 0)
                types     = [l.get("type", "") for l in t_legs]
                mode_str  = "KTX·열차" if "train" in types else ("버스" if "bus" in types else "지하철")
                return f"{comfort_abs[p]:.0f}점 ({mode_str}·도보{walk_km:.1f}km·환승{transfers}회)"
            return f"{comfort_abs[p]:.0f}점 (자동차·도어투도어)"

        comfort_meta = {'label': '탑승 편안함', 'unit': '점',
                        **{p: _comfort_label(p) for p in providers}}

        def _safety_label(p: str) -> str:
            if p == 'odsay':
                t_legs = [l for l in (results[p].transit_legs or []) if l.get("type") != "walk"]
                types  = [l.get("type", "") for l in t_legs]
                mode_desc = ("KTX·열차·전용선로" if "train" in types
                             else ("지하철·전용선로" if "subway" in types else "버스·도로운행"))
                return f"{safety_abs[p]:.0f}점 ({mode_desc})"
            return f"{safety_abs[p]:.0f}점 (자동차·교통사고 위험)"

        safe_meta = {'label': '교통안전 (통계 기반)', 'unit': '점',
                     **{p: _safety_label(p) for p in providers}}
    else:
        comfort_meta = {'label': '고속도로 비율', 'unit': '%',
                        **{p: f"{ratios[p]*100:.1f}%" for p in providers}}
        safe_meta    = {'label': '평균속도', 'unit': 'km/h',
                        **{p: f"{round(speeds[p],1)}km/h" for p in providers}}

    dim_meta = {
        'cheap':   {'label': '통행료',   'unit': '원',
                    **{p: f"{int(results[p].toll_fee):,}원" for p in providers}},
        'fast':    {'label': '소요시간', 'unit': '분',
                    **{p: _fmt_time(results[p].duration_min) for p in providers}},
        'comfort': comfort_meta,
        'safe':    safe_meta,
    }

    final = {
        p: round(sum(norm_w.get(d, 0) * breakdown[p][d] for d in dims), 2)
        for p in providers
    }
    return final, breakdown, dim_meta


def _resolve_coords(query: str):
    """주소 또는 장소명으로 좌표를 반환한다.

    순서:
        1. 카카오 주소 검색 (도로명/지번 주소)
        2. 카카오 키워드 검색 fallback (장소명: 서울시청, 강남역 등)
    """
    # 1. 주소 검색
    coords = _kakao.get_coords_from_address(query)
    if coords:
        return coords
    # 2. 장소명 키워드 검색
    try:
        result = _kakao.search_place(query, size=1)
        docs   = result.get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception:
        pass
    return None


@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    resp.headers["Expires"]       = "0"
    return resp


@app.route("/api/ping")
def ping():
    """서버 연결 확인용 엔드포인트."""
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    """장소 자동완성 (카카오 키워드 검색)."""
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    try:
        result = _kakao.search_place(query, size=5)
        return jsonify([
            {
                "name":    d.get("place_name", ""),
                "address": d.get("road_address_name") or d.get("address_name", ""),
                "lat":     float(d["y"]),
                "lon":     float(d["x"]),
            }
            for d in result.get("documents", [])
        ])
    except Exception:
        return jsonify([])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """출발지/목적지·교통수단·선호도 가중치로 카카오·T맵을 비교 분석한다."""
    data         = request.get_json(force=True)
    origin_q     = data.get("origin", "").strip()
    dest_q       = data.get("destination", "").strip()
    o_lat        = data.get("origin_lat")
    o_lon        = data.get("origin_lon")
    d_lat        = data.get("dest_lat")
    d_lon        = data.get("dest_lon")
    vehicle_type      = data.get("vehicle_type", "car")
    selected_prefs    = data.get("selected_prefs", [])            # 선택한 선호도 목록
    selected_services = data.get("selected_services", ["kakao", "tmap"])  # 선택한 서비스
    weights           = _weights_from_selection(selected_prefs)   # 백엔드에서 가중치 계산

    if not origin_q or not dest_q:
        return jsonify({"error": "출발지와 목적지를 입력해주세요."}), 400

    if not (o_lat and o_lon):
        coords = _resolve_coords(origin_q)
        if not coords:
            return jsonify({"error": f"출발지를 찾을 수 없습니다: '{origin_q}'"}), 400
        o_lat, o_lon = coords

    if not (d_lat and d_lon):
        coords = _resolve_coords(dest_q)
        if not coords:
            return jsonify({"error": f"목적지를 찾을 수 없습니다: '{dest_q}'"}), 400
        d_lat, d_lon = coords

    origin = {"lat": float(o_lat), "lon": float(o_lon), "name": origin_q}
    dest   = {"lat": float(d_lat), "lon": float(d_lon), "name": dest_q}

    # 선호도 → ODsay 경로 선택 기준 변환
    # 'cheap' 선호 선택 시 요금 최저 경로, 'fast' 선택 시 최단시간 경로 사용
    _PREF_MAP = {"cheap": "cheap", "fast": "fast", "comfort": "comfort"}
    transit_pref = next((_PREF_MAP[p] for p in selected_prefs if p in _PREF_MAP), "optimal")

    try:
        results = _setup.fetch_both(
            origin, dest,
            vehicle_type=vehicle_type,
            services=selected_services,
            preference=transit_pref,
        )
    except RuntimeError as e:
        msg = str(e)
        # 쿼터 초과: 사용자 친화적 메시지
        if "한도 초과" in msg or "quota" in msg.lower():
            return jsonify({
                "error": "ODsay 대중교통 API 일일 호출 한도가 초과됐습니다. "
                         "내일 자정(00:00) 이후 다시 시도해 주세요. "
                         "(lab.odsay.com에서 유료 플랜 전환 시 즉시 사용 가능)"
            }), 503
        return jsonify({"error": f"경로 조회 오류: {msg}"}), 500
    except Exception as e:
        return jsonify({"error": f"API 오류: {e}"}), 500

    if not results:
        if vehicle_type == "bike":
            only_kakao = "kakao" in selected_services and "tmap" not in selected_services
            only_tmap  = "tmap" in selected_services and "kakao" not in selected_services
            if only_kakao:
                reason = "카카오 Mobility API는 자전거 경로를 지원하지 않습니다."
            elif only_tmap:
                reason = "T맵 자전거 라우팅 API는 현재 API 키로 지원되지 않습니다."
            else:
                reason = "선택한 지도 서비스에서 자전거 경로를 지원하지 않습니다."
            return jsonify({
                "error": f"자전거 경로 조회에 실패했습니다.\n{reason}\n자동차 또는 대중교통을 이용해 주세요."
            }), 503
        if vehicle_type == "walk":
            return jsonify({
                "error": "도보 경로 조회에 실패했습니다.\n"
                         "매우 장거리 도보 경로는 지원되지 않을 수 있습니다."
            }), 503
        return jsonify({"error": "경로 조회에 실패했습니다."}), 500

    pref_scores, pref_breakdown, dim_meta = _calc_pref_scores(results, weights)
    base_result = _analysis.compare(results)
    winner = max(pref_scores, key=pref_scores.get) if pref_scores else base_result.recommendation

    notices = []
    if vehicle_type in ("walk", "bike") and "kakao" not in results:
        mode_label = "도보" if vehicle_type == "walk" else "자전거"
        notices.append(
            f"카카오 Mobility API는 {mode_label} 경로를 지원하지 않아 T맵 단독으로 표시합니다."
        )

    return jsonify({
        "origin":         origin_q,
        "destination":    dest_q,
        "origin_lat":     float(o_lat),
        "origin_lon":     float(o_lon),
        "dest_lat":       float(d_lat),
        "dest_lon":       float(d_lon),
        "vehicle_type":   vehicle_type,
        "selected_prefs":  selected_prefs,
        "weights":         weights,
        "recommendation": winner,
        "pref_scores":    pref_scores,
        "pref_breakdown": pref_breakdown,
        "dim_meta":       dim_meta,
        "base_scores":    {k: round(v, 2) for k, v in base_result.scores.items()},
        "notices":        notices,
        "details": {
            p: {
                "distance_km":  round(r.distance_km, 2),
                "duration_min": round(r.duration_min, 1),
                "toll_fee":     r.toll_fee,
                "taxi_fee":     r.taxi_fee,
                "transit_legs": r.transit_legs,
            }
            for p, r in results.items()
        },
    })


@app.route("/health")
def health_check():
    """서버 상태 확인용 엔드포인트."""
    return jsonify({"status": "ok", "message": "길잡이 AI 서버가 정상 작동 중입니다."})


@app.route("/api/ask", methods=["POST"])
def ask_ai():
    """질문을 받아 간단한 AI 응답을 반환한다."""
    data = request.get_json(silent=True) or {}
    user_question = str(data.get("question", "")).strip()
    if not user_question:
        return jsonify({"error": "질문을 입력해주세요."}), 400

    ai_answer = f"'{user_question}'에 대한 AI의 답변입니다."
    return jsonify({"answer": ai_answer})


if __name__ == "__main__":
    print("\n" + "=" * 52)
    print("  지도 서비스 경로 분석기")
    print("  http://localhost:8080 에서 접속하세요")
    print("=" * 52 + "\n")
    app.run(debug=False, port=8080, threaded=True)
