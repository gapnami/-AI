import json
import os
from datetime import datetime


def save_json(data: dict, directory: str, filename: str = None) -> str:
    os.makedirs(directory, exist_ok=True)
    if filename is None:
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_duration(seconds: int) -> str:
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}시간 {m}분 {s}초"
    return f"{m}분 {s}초"


def format_distance(meters: int) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f}km"
    return f"{meters}m"
