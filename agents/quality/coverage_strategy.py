"""Coverage risk strategy for formal production modules.

The strategy only reads coverage artifacts and emits findings/candidates. It
does not act as a CI gate and does not modify production code.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import normalize_candidate, read_json, write_json


FORMAL_PRODUCT_MODULES = (
    "src/preprocess_phase0.py",
    "src/downscale_frames.py",
    "src/sfm_colmap.py",
    "src/train_3dgs.py",
    "src/export_ply.py",
    "src/export_ply_unity.py",
)


class CoverageStrategy:
    """Analyze coverage.py JSON reports and propose test-work candidates."""

    def __init__(
        self,
        formal_modules: tuple[str, ...] | None = None,
        min_file_coverage: float = 80.0,
        critical_file_coverage: float = 50.0,
    ):
        self.formal_modules = formal_modules or FORMAL_PRODUCT_MODULES
        self.min_file_coverage = float(min_file_coverage)
        self.critical_file_coverage = float(critical_file_coverage)

    def analyze(self, coverage_report_path: str | Path) -> dict[str, Any]:
        """Return coverage findings and candidate proposals for the report."""
        report_path = Path(coverage_report_path)
        if not report_path.exists():
            return self._result(
                report_path=report_path,
                status="missing_report",
                findings=[
                    {
                        "issue": "coverage_report_missing",
                        "severity": "high",
                        "path": str(report_path),
                        "message": "coverage JSON report does not exist",
                    }
                ],
                ignored_file_count=0,
            )

        try:
            report = read_json(report_path, expect_object=True)
        except Exception as exc:
            return self._result(
                report_path=report_path,
                status="invalid_report",
                findings=[
                    {
                        "issue": "coverage_report_invalid",
                        "severity": "high",
                        "path": str(report_path),
                        "message": str(exc),
                    }
                ],
                ignored_file_count=0,
            )

        files = report.get("files", {})
        if not isinstance(files, dict):
            return self._result(
                report_path=report_path,
                status="invalid_report",
                findings=[
                    {
                        "issue": "coverage_files_invalid",
                        "severity": "high",
                        "path": str(report_path),
                        "message": "coverage report field 'files' must be an object",
                    }
                ],
                ignored_file_count=0,
            )

        normalized_files = {self._normalize_path(path): data for path, data in files.items()}
        formal_set = set(self.formal_modules)
        ignored_file_count = len([path for path in normalized_files if path not in formal_set])
        findings = self._formal_findings(normalized_files)
        status = "pass" if not findings else "needs_tests"
        return self._result(
            report_path=report_path,
            status=status,
            findings=findings,
            ignored_file_count=ignored_file_count,
        )

    def write_report(self, coverage_report_path: str | Path, output_path: str | Path) -> dict[str, Any]:
        """Analyze and write a stable JSON report."""
        payload = self.analyze(coverage_report_path)
        write_json(output_path, payload)
        return payload

    def _formal_findings(self, normalized_files: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for module_path in self.formal_modules:
            entry = normalized_files.get(module_path)
            if entry is None:
                findings.append(
                    {
                        "issue": "formal_module_missing_from_report",
                        "severity": "high",
                        "module": module_path,
                        "message": "formal production module is absent from coverage report",
                    }
                )
                continue

            summary = entry.get("summary", {}) if isinstance(entry, dict) else {}
            percent = self._percent(summary)
            missing_lines = entry.get("missing_lines", []) if isinstance(entry, dict) else []
            if percent < self.min_file_coverage:
                findings.append(
                    {
                        "issue": "formal_module_below_threshold",
                        "severity": "high" if percent < self.critical_file_coverage else "medium",
                        "module": module_path,
                        "coverage": round(percent, 2),
                        "threshold": self.min_file_coverage,
                        "missing_line_count": len(missing_lines) if isinstance(missing_lines, list) else 0,
                        "missing_lines_sample": missing_lines[:20] if isinstance(missing_lines, list) else [],
                        "message": "formal production module needs more tests before mainline promotion",
                    }
                )
        return findings

    def _result(
        self,
        report_path: Path,
        status: str,
        findings: list[dict[str, Any]],
        ignored_file_count: int,
    ) -> dict[str, Any]:
        generated_at = datetime.now().isoformat()
        candidates = self._build_candidates(status, findings)
        return {
            "schema_version": 1,
            "strategy": "CoverageStrategy",
            "generated_at": generated_at,
            "coverage_report": str(report_path),
            "formal_modules": list(self.formal_modules),
            "thresholds": {
                "min_file_coverage": self.min_file_coverage,
                "critical_file_coverage": self.critical_file_coverage,
            },
            "status": status,
            "ignored_file_count": ignored_file_count,
            "finding_count": len(findings),
            "findings": findings,
            "candidates": candidates,
        }

    def _build_candidates(self, status: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not findings:
            return []

        blocked_by = ["coverage_report_missing"] if status == "missing_report" else []
        candidate = {
            "candidate_id": "COV-001",
            "source_module": "CoverageStrategy",
            "scope": "quality",
            "proposal_type": "coverage_risk",
            "title": "補正式主線 coverage 缺口",
            "rationale": self._candidate_rationale(status, findings),
            "params": {
                "formal_modules": list(self.formal_modules),
                "min_file_coverage": self.min_file_coverage,
            },
            "expected_gain": "reduce untested return, exception, and branch-path regressions",
            "expected_risk": "blocks promotion until meaningful tests are added",
            "estimated_cost": "medium",
            "blocked_by": blocked_by,
            "evidence": {
                "status": status,
                "finding_count": len(findings),
                "findings": findings,
            },
            "confidence": 0.9 if status == "needs_tests" else 0.75,
        }
        return [normalize_candidate(candidate, source_path="CoverageStrategy")]

    @staticmethod
    def _candidate_rationale(status: str, findings: list[dict[str, Any]]) -> str:
        if status == "missing_report":
            return "coverage report is missing; run coverage before changing production mainline"
        if status == "invalid_report":
            return "coverage report is invalid; regenerate coverage JSON before evaluation"
        modules = [item.get("module") for item in findings if item.get("module")]
        if modules:
            return f"formal modules below coverage threshold: {', '.join(modules[:4])}"
        return "coverage findings require test-first remediation"

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        if "/src/" in normalized:
            return "src/" + normalized.split("/src/", 1)[1]
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _percent(summary: dict[str, Any]) -> float:
        raw = summary.get("percent_covered", summary.get("percent_statements_covered", 0.0))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
