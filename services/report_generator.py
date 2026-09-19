import os
import json
from datetime import datetime
from models.analysis_result import AnalysisResult
from utils.logger import get_logger

logger = get_logger(__name__)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "reports")


class ReportGenerator:
    def generate(self, result: AnalysisResult) -> str:
        os.makedirs(REPORT_DIR, exist_ok=True)
        filename = f"report_{result.route_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = os.path.join(REPORT_DIR, filename)
        report = {
            "route_id": result.route_id,
            "generated_at": datetime.now().isoformat(),
            "recommendation": result.recommendation,
            "scores": result.scores,
            "details": result.details,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"Report saved: {path}")
        return path
