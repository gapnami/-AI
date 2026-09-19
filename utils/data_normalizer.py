from models.route_model import RouteResult


def normalize_kakao_response(raw: dict) -> RouteResult:
    routes = raw.get("routes", [{}])[0]
    summary = routes.get("summary", {})
    return RouteResult(
        provider="kakao",
        distance_m=summary.get("distance", 0),
        duration_s=summary.get("duration", 0),
        toll_fee=summary.get("fare", {}).get("toll", 0),
        taxi_fee=summary.get("fare", {}).get("taxi", 0),
        raw=raw,
    )


def normalize_tmap_response(raw: dict) -> RouteResult:
    features = raw.get("features", [])
    props = features[0].get("properties", {}) if features else {}
    return RouteResult(
        provider="tmap",
        distance_m=props.get("totalDistance", 0),
        duration_s=props.get("totalTime", 0),
        toll_fee=props.get("totalFare", 0),
        taxi_fee=0,
        raw=raw,
    )
