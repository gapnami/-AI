import logging
import os
from dataclasses import dataclass, field
from typing import Optional, List

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 환경 헬퍼
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val is None:
        return default
    v = val.strip()
    # 환경파일에 값에 작은따옴표나 큰따옴표로 감싸진 경우를 처리
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1].strip()
    return v

def _get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

def _get_env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# 개별 API 설정 dataclass
# ---------------------------------------------------------------------------

@dataclass
class APISettings:
    """단일 API 서비스에 대한 설정."""
    name: str
    api_key: str
    timeout: int = 10
    max_retries: int = 3
    rate_limit: int = 100        # 분당 최대 호출 수
    retry_delay: float = 1.0     # 재시도 간격(초)
    endpoints: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """설정 오류 목록 반환. 빈 리스트면 정상."""
        errors: list[str] = []
        if not self.api_key:
            errors.append(f"[{self.name}] API 키가 설정되지 않았습니다.")
        if self.timeout <= 0:
            errors.append(f"[{self.name}] timeout은 양수여야 합니다: {self.timeout}")
        if self.max_retries < 0:
            errors.append(f"[{self.name}] max_retries는 0 이상이어야 합니다: {self.max_retries}")
        if self.rate_limit <= 0:
            errors.append(f"[{self.name}] rate_limit은 양수여야 합니다: {self.rate_limit}")
        return errors


# ---------------------------------------------------------------------------
# 로깅 설정 dataclass
# ---------------------------------------------------------------------------

@dataclass
class LoggingSettings:
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    log_to_file: bool = True
    log_dir: str = "output/logs"

    def get_level(self) -> int:
        return getattr(logging, self.level.upper(), logging.INFO)

    def validate(self) -> list[str]:
        errors: list[str] = []
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.level.upper() not in valid_levels:
            errors.append(f"[Logging] 유효하지 않은 로그 레벨: {self.level}")
        return errors


# ---------------------------------------------------------------------------
# 전체 앱 설정 dataclass
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    """애플리케이션 전체 설정."""
    env: str                          # "test" | "production"
    kakao: APISettings
    tmap: APISettings
    logging: LoggingSettings
    odsay: Optional[APISettings] = None   # ODsay 대중교통 API (선택)

    # ── 공통 설정 ──────────────────────────────────────────────────────────
    api_timeout: int = 10
    max_retries: int = 3
    rate_limit: int = 100

    def is_test(self) -> bool:
        return self.env == "test"

    def is_production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        """모든 설정을 검증하고 오류가 있으면 ValueError를 발생시킨다."""
        errors: list[str] = []
        errors.extend(self.kakao.validate())
        errors.extend(self.tmap.validate())
        errors.extend(self.logging.validate())

        if self.env not in ("test", "production"):
            errors.append(f"[App] ENV는 'test' 또는 'production'이어야 합니다: {self.env}")

        if errors:
            raise ValueError("설정 오류:\n" + "\n".join(f"  - {e}" for e in errors))

    def summary(self) -> str:
        """현재 설정 요약을 문자열로 반환 (API 키는 마스킹)."""
        def mask(key: str) -> str:
            return key[:6] + "***" if len(key) > 6 else "***"

        lines = [
            f"환경(ENV)         : {self.env}",
            f"로그 레벨         : {self.logging.level}",
            "",
            f"[Kakao] 키        : {mask(self.kakao.api_key)}",
            f"[Kakao] Timeout   : {self.kakao.timeout}s",
            f"[Kakao] Retries   : {self.kakao.max_retries}",
            f"[Kakao] RateLimit : {self.kakao.rate_limit}회/분",
            f"[Kakao] Endpoints : {self.kakao.endpoints}",
            "",
            f"[TMap]  키        : {mask(self.tmap.api_key)}",
            f"[TMap]  Timeout   : {self.tmap.timeout}s",
            f"[TMap]  Retries   : {self.tmap.max_retries}",
            f"[TMap]  RateLimit : {self.tmap.rate_limit}회/분",
            f"[TMap]  Endpoints : {self.tmap.endpoints}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 설정 팩토리 함수
# ---------------------------------------------------------------------------

def _build_kakao_settings() -> APISettings:
    return APISettings(
        name="KakaoMap",
        api_key=_get_env("KAKAO_REST_API_KEY"),
        timeout=_get_env_int("KAKAO_TIMEOUT", 10),
        max_retries=_get_env_int("MAX_RETRIES", 3),
        rate_limit=_get_env_int("KAKAO_RATE_LIMIT", 100),
        retry_delay=float(os.getenv("RETRY_DELAY", "1.0")),
        endpoints={
            "local":      "https://dapi.kakao.com/v2/local",
            "directions": "https://apis-navi.kakaomobility.com/v1/directions",
            "waypoints":  "https://apis-navi.kakaomobility.com/v1/waypoints/directions",
        },
    )



def _build_odsay_settings() -> Optional[APISettings]:
    key = _get_env("ODSAY_API_KEY", "")
    if not key:
        return None
    return APISettings(
        name="ODsay",
        api_key=key,
        timeout=_get_env_int("ODSAY_TIMEOUT", 15),
        max_retries=_get_env_int("MAX_RETRIES", 3),
        rate_limit=_get_env_int("RATE_LIMIT", 100),
        endpoints={"transit": "https://api.odsay.com/v1/api/searchPubTransPathT"},
    )


def _build_tmap_settings() -> APISettings:
    return APISettings(
        name="TMap",
        api_key=_get_env("TMAP_APP_KEY"),
        timeout=_get_env_int("TMAP_TIMEOUT", 10),
        max_retries=_get_env_int("MAX_RETRIES", 3),
        rate_limit=_get_env_int("TMAP_RATE_LIMIT", 100),
        retry_delay=float(os.getenv("RETRY_DELAY", "1.0")),
        endpoints={
            "route":      "https://apis.openapi.sk.com/tmap/routes/pedestrian",
            "route_car":  "https://apis.openapi.sk.com/tmap/routes",
            "poi":        "https://apis.openapi.sk.com/tmap/pois",
            "reverse_gc": "https://apis.openapi.sk.com/tmap/geo/reversegeocoding",
        },
    )


def _build_logging_settings() -> LoggingSettings:
    return LoggingSettings(
        level=_get_env("LOG_LEVEL", "INFO"),
        log_to_file=_get_env_bool("LOG_TO_FILE", True),
        log_dir=_get_env("LOG_DIR", "output/logs"),
    )


def load_config(env: Optional[str] = None) -> AppConfig:
    """
    환경변수에서 AppConfig를 빌드하고 검증한다.

    Args:
        env: 'test' 또는 'production'. None이면 ENV 환경변수를 사용.
    Returns:
        검증된 AppConfig 인스턴스
    Raises:
        ValueError: 설정 오류 발생 시
    """
    resolved_env = env or _get_env("ENV", "production")
    config = AppConfig(
        env=resolved_env,
        kakao=_build_kakao_settings(),
        tmap=_build_tmap_settings(),
        odsay=_build_odsay_settings(),
        logging=_build_logging_settings(),
        api_timeout=_get_env_int("API_TIMEOUT", 10),
        max_retries=_get_env_int("MAX_RETRIES", 3),
        rate_limit=_get_env_int("RATE_LIMIT", 100),
    )

    # 테스트 모드에서는 키 검증을 생략
    if not config.is_test():
        config.validate()

    return config


# ---------------------------------------------------------------------------
# 모듈 로드 시 기본 config 인스턴스 생성 (하위 호환용 단순 상수도 제공)
# ---------------------------------------------------------------------------

config = load_config()

# 하위 호환 상수 (기존 핸들러 코드가 직접 import 하던 값)
KAKAO_API_KEY: str = config.kakao.api_key
TMAP_API_KEY: str = config.tmap.api_key
KAKAO_BASE_URL: str = config.kakao.endpoints["directions"]
TMAP_BASE_URL: str = config.tmap.endpoints["route"]
REQUEST_TIMEOUT: int = config.api_timeout
MAX_RETRIES: int = config.max_retries
