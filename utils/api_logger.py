"""
구조화된 API 분석 로깅 시스템.

Features:
  - 파일(Rotating) + 콘솔 멀티 핸들러
  - colorama 기반 색상 콘솔 출력
  - ISO 8601 타임스탬프
  - JSON / CSV 내보내기
  - 스레드 안전 (threading.Lock)
  - 분석 요약 및 테이블 출력
"""

import csv
import io
import json
import logging
import os
import threading
import traceback
from datetime import datetime
from enum import Enum
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

# ── 경로 상수 ─────────────────────────────────────────────────────────────────
_LOG_DIR  = os.path.join(os.path.dirname(__file__), "..", "output", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "api_analysis.log")
os.makedirs(_LOG_DIR, exist_ok=True)


# ============================================================
# Enum 정의
# ============================================================

class APIStatus(str, Enum):
    SUCCESS         = "SUCCESS"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILURE         = "FAILURE"
    TIMEOUT         = "TIMEOUT"

    def color(self) -> str:
        return {
            "SUCCESS":         Fore.GREEN,
            "PARTIAL_FAILURE": Fore.YELLOW,
            "FAILURE":         Fore.RED,
            "TIMEOUT":         Fore.MAGENTA,
        }[self.value]


class LogLevel(str, Enum):
    DEBUG   = "DEBUG"
    INFO    = "INFO"
    WARNING = "WARNING"
    ERROR   = "ERROR"

    def to_logging(self) -> int:
        return getattr(logging, self.value)

    def color(self) -> str:
        return {
            "DEBUG":   Fore.CYAN,
            "INFO":    Fore.WHITE,
            "WARNING": Fore.YELLOW,
            "ERROR":   Fore.RED,
        }[self.value]


# ============================================================
# 색상 콘솔 포매터
# ============================================================

class _ColorFormatter(logging.Formatter):
    _LEVEL_COLORS = {
        logging.DEBUG:   Fore.CYAN,
        logging.INFO:    Fore.WHITE,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR:   Fore.RED,
        logging.CRITICAL:Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color   = self._LEVEL_COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"


# ============================================================
# APIAnalysisLogger
# ============================================================

class APIAnalysisLogger:
    """카카오맵 / T맵 API 호출 및 분석 결과를 구조화하여 기록하는 로거.

    Args:
        log_file: 로그 파일 경로 (기본: output/logs/api_analysis.log)
        level:    로그 레벨 (기본: INFO)
        max_bytes: 로그 파일 최대 크기 (기본: 5 MB)
        backup_count: 로테이션 백업 파일 수 (기본: 5)

    Example:
        >>> logger = APIAnalysisLogger()
        >>> logger.log_api_call(
        ...     api_name="kakao",
        ...     endpoint="directions",
        ...     parameters={"start": "강남역", "end": "인천공항"},
        ...     status=APIStatus.SUCCESS,
        ...     response_time=245.67,
        ...     response_data={"distance": 47320},
        ... )
    """

    def __init__(
        self,
        log_file:     str = _LOG_FILE,
        level:        LogLevel = LogLevel.INFO,
        max_bytes:    int = 5 * 1024 * 1024,   # 5 MB
        backup_count: int = 5,
    ) -> None:
        self.log_file = log_file
        self._lock    = threading.Lock()
        self._records: List[Dict[str, Any]] = []   # 인메모리 로그 저장소

        # ── Python 로거 설정 ─────────────────────────────────
        self._logger = logging.getLogger("APIAnalysisLogger")
        self._logger.setLevel(level.to_logging())
        self._logger.propagate = False

        if not self._logger.handlers:
            fmt      = "%(asctime)s | %(levelname)-8s | %(message)s"
            iso_fmt  = "%Y-%m-%dT%H:%M:%S"

            # 파일 핸들러 (Rotating, UTF-8)
            fh = RotatingFileHandler(
                log_file, maxBytes=max_bytes,
                backupCount=backup_count, encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(fmt, datefmt=iso_fmt))

            # 콘솔 핸들러 (색상)
            ch = logging.StreamHandler()
            ch.setLevel(level.to_logging())
            ch.setFormatter(_ColorFormatter(fmt, datefmt=iso_fmt))

            self._logger.addHandler(fh)
            self._logger.addHandler(ch)

        self._logger.info("APIAnalysisLogger 초기화 완료 → %s", log_file)

    # =========================================================
    # 내부 유틸
    # =========================================================

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="microseconds")

    def _store(self, record: Dict[str, Any]) -> None:
        """스레드 안전하게 인메모리 레코드에 추가."""
        with self._lock:
            self._records.append(record)

    # =========================================================
    # 1. API 호출 로깅
    # =========================================================

    def log_api_call(
        self,
        api_name:      str,
        endpoint:      str,
        parameters:    Dict,
        status:        APIStatus,
        response_time: float,                    # ms
        response_data: Optional[Dict] = None,
        error_msg:     Optional[str]  = None,
        include_trace: bool           = False,
    ) -> Dict:
        """API 호출 정보를 JSON 구조로 기록한다.

        Args:
            api_name:      API 서비스명 ('kakao' | 'tmap')
            endpoint:      호출 엔드포인트
            parameters:    요청 파라미터
            status:        APIStatus Enum
            response_time: 응답 시간 (밀리초)
            response_data: 응답 데이터 (선택)
            error_msg:     오류 메시지 (선택)
            include_trace: 스택 트레이스 포함 여부

        Returns:
            기록된 로그 레코드 Dict
        """
        response_bytes = (
            len(json.dumps(response_data, ensure_ascii=False).encode())
            if response_data else 0
        )
        trace = traceback.format_exc() if include_trace and error_msg else None

        record: Dict[str, Any] = {
            "timestamp":           self._now(),
            "level":               "ERROR" if status == APIStatus.FAILURE else "INFO",
            "api_name":            api_name,
            "endpoint":            endpoint,
            "status":              status.value,
            "response_time_ms":    round(response_time, 3),
            "response_size_bytes": response_bytes,
            "error":               error_msg,
            "stack_trace":         trace,
            "request_params":      parameters,
        }

        self._store(record)

        # 콘솔 & 파일 로깅
        status_str = f"{status.color()}[{status.value}]{Style.RESET_ALL}"
        msg = (
            f"{status_str} {api_name.upper()} | {endpoint} | "
            f"{response_time:.1f}ms | {response_bytes}B"
        )
        if error_msg:
            self._logger.error("%s | ERR: %s", msg, error_msg)
        elif status == APIStatus.TIMEOUT:
            self._logger.warning(msg)
        else:
            self._logger.info(msg)

        return record

    # =========================================================
    # 2. 분석 단계 로깅
    # =========================================================

    def log_analysis_stage(self, stage_name: str, results: Dict[str, Any]) -> None:
        """분석 파이프라인의 단계별 결과를 기록한다.

        Args:
            stage_name: 단계명 ('가중치_기반_평가', 'AHP_분석' 등)
            results:    단계 결과 데이터
        """
        record: Dict[str, Any] = {
            "timestamp":  self._now(),
            "level":      "INFO",
            "type":       "analysis_stage",
            "stage_name": stage_name,
            "results":    results,
        }
        self._store(record)
        self._logger.info(
            "[분석단계] %s | keys=%s",
            stage_name, list(results.keys()),
        )

    # =========================================================
    # 3. 벤치마크 결과 로깅
    # =========================================================

    def log_benchmark_result(
        self,
        api_name: str,
        metric:   str,
        value:    Any,
    ) -> None:
        """벤치마크 측정값을 기록한다.

        Args:
            api_name: API 서비스명
            metric:   측정 항목 ('response_time', 'accuracy', 'freshness' 등)
            value:    측정값
        """
        record: Dict[str, Any] = {
            "timestamp": self._now(),
            "level":     "INFO",
            "type":      "benchmark",
            "api_name":  api_name,
            "metric":    metric,
            "value":     value,
        }
        self._store(record)
        self._logger.info(
            "[벤치마크] %s | %s = %s",
            api_name.upper(), metric, value,
        )

    # =========================================================
    # 4. 분석 요약 반환
    # =========================================================

    def get_analysis_summary(self) -> Dict[str, Any]:
        """수집된 로그를 기반으로 종합 분석 요약을 반환한다.

        Returns:
            {
                'total_calls':      int,
                'success_rate':     float (%),
                'avg_response_ms':  float,
                'per_api':          { api_name: { calls, success, avg_ms } },
                'analysis_stages':  List[str],
                'benchmarks':       Dict,
            }
        """
        with self._lock:
            records = list(self._records)

        api_calls   = [r for r in records if "endpoint" in r]
        stages      = [r for r in records if r.get("type") == "analysis_stage"]
        benchmarks  = [r for r in records if r.get("type") == "benchmark"]

        total   = len(api_calls)
        success = sum(1 for r in api_calls if r["status"] == APIStatus.SUCCESS.value)
        times   = [r["response_time_ms"] for r in api_calls]

        # API별 집계
        per_api: Dict[str, Any] = {}
        for r in api_calls:
            name = r["api_name"]
            if name not in per_api:
                per_api[name] = {"calls": 0, "success": 0, "times": []}
            per_api[name]["calls"]   += 1
            per_api[name]["times"].append(r["response_time_ms"])
            if r["status"] == APIStatus.SUCCESS.value:
                per_api[name]["success"] += 1

        per_api_summary = {
            name: {
                "calls":       v["calls"],
                "success":     v["success"],
                "success_rate": round(v["success"] / v["calls"] * 100, 1) if v["calls"] else 0,
                "avg_ms":      round(sum(v["times"]) / len(v["times"]), 2) if v["times"] else 0,
            }
            for name, v in per_api.items()
        }

        bench_summary: Dict[str, Dict] = {}
        for b in benchmarks:
            key = f"{b['api_name']}.{b['metric']}"
            bench_summary[key] = b["value"]

        return {
            "total_calls":     total,
            "success_count":   success,
            "success_rate":    round(success / total * 100, 1) if total else 0.0,
            "avg_response_ms": round(sum(times) / len(times), 2) if times else 0.0,
            "per_api":         per_api_summary,
            "analysis_stages": [r["stage_name"] for r in stages],
            "benchmarks":      bench_summary,
        }

    # =========================================================
    # 5. 로그 내보내기 (JSON / CSV)
    # =========================================================

    def export_logs(self, format: str = "json") -> str:
        """수집된 로그를 JSON 또는 CSV 문자열로 내보낸다.

        Args:
            format: 'json' | 'csv'

        Returns:
            직렬화된 문자열

        Raises:
            ValueError: 지원하지 않는 format
        """
        with self._lock:
            records = list(self._records)

        if format == "json":
            return json.dumps(
                {"exported_at": self._now(), "records": records},
                ensure_ascii=False, indent=2,
            )

        if format == "csv":
            if not records:
                return ""
            buf = io.StringIO()
            # 모든 레코드의 키 합집합으로 헤더 구성
            all_keys: List[str] = []
            for r in records:
                for k in r:
                    if k not in all_keys:
                        all_keys.append(k)

            writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                flat = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()}
                writer.writerow(flat)
            return buf.getvalue()

        raise ValueError(f"지원하지 않는 format: {format!r}. 'json' 또는 'csv' 사용.")

    # =========================================================
    # 6. 콘솔 요약 테이블 출력
    # =========================================================

    def print_summary(self) -> None:
        """분석 결과 요약을 컬러 테이블로 콘솔에 출력한다."""
        summary = self.get_analysis_summary()
        W = 58  # 테이블 너비

        def rule(char: str = "-") -> str:
            return Fore.CYAN + char * W + Style.RESET_ALL

        def row(label: str, value: Any, color: str = Fore.WHITE) -> str:
            label_s = f"{label:<28}"
            value_s = f"{color}{str(value):>26}{Style.RESET_ALL}"
            return f"| {label_s} | {value_s} |"

        print(rule("="))
        print(Fore.CYAN + Style.BRIGHT + " API 분석 로그 요약".center(W) + Style.RESET_ALL)
        print(rule("="))

        sr_color = (
            Fore.GREEN if summary["success_rate"] >= 90
            else Fore.YELLOW if summary["success_rate"] >= 70
            else Fore.RED
        )
        print(row("총 API 호출 수",    summary["total_calls"]))
        print(row("성공 건수",          summary["success_count"],  Fore.GREEN))
        print(row("성공률",             f"{summary['success_rate']}%",  sr_color))
        print(row("평균 응답시간",      f"{summary['avg_response_ms']}ms"))
        print(rule())

        for api, stat in summary["per_api"].items():
            sr = stat["success_rate"]
            c  = Fore.GREEN if sr >= 90 else Fore.YELLOW if sr >= 70 else Fore.RED
            print(Fore.CYAN + f"  [{api.upper()}]" + Style.RESET_ALL)
            print(row("  호출 수",     stat["calls"]))
            print(row("  성공률",      f"{sr}%", c))
            print(row("  평균 응답",   f"{stat['avg_ms']}ms"))
        print(rule())

        if summary["analysis_stages"]:
            print(Fore.CYAN + " 분석 단계" + Style.RESET_ALL)
            for stage in summary["analysis_stages"]:
                print(f"  {Fore.WHITE}• {stage}{Style.RESET_ALL}")
            print(rule())

        if summary["benchmarks"]:
            print(Fore.CYAN + " 벤치마크" + Style.RESET_ALL)
            for key, val in summary["benchmarks"].items():
                print(row(f"  {key}", val))
            print(rule())

        print(rule("="))
