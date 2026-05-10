from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agents.quality.coverage_strategy import CoverageStrategy


def write_coverage(path: Path, files: dict) -> Path:
    path.write_text(
        json.dumps(
            {
                "meta": {"format": 3},
                "files": files,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def file_entry(percent: float, missing_lines: list[int] | None = None) -> dict:
    return {
        "summary": {
            "covered_lines": 10,
            "num_statements": 10,
            "percent_covered": percent,
            "missing_lines": len(missing_lines or []),
        },
        "missing_lines": missing_lines or [],
    }


class CoverageStrategyTests(unittest.TestCase):
    def test_analyze_reports_only_formal_module_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = write_coverage(
                root / "coverage.json",
                {
                    r"src\preprocess_phase0.py": file_entry(32.0, [10, 11, 12]),
                    r"src\downscale_frames.py": file_entry(91.0),
                    r"src\train_3dgs.py": file_entry(81.0),
                    r"src\export_ply.py": file_entry(82.0),
                    r"src\export_ply_unity.py": file_entry(41.0, [20]),
                    r"scripts\one_off.py": file_entry(0.0, [1, 2, 3]),
                },
            )

            result = CoverageStrategy().analyze(report)

            self.assertEqual(result["status"], "needs_tests")
            self.assertEqual(result["ignored_file_count"], 1)
            issues = {(item["issue"], item.get("module")) for item in result["findings"]}
            self.assertIn(("formal_module_below_threshold", "src/preprocess_phase0.py"), issues)
            self.assertIn(("formal_module_below_threshold", "src/export_ply_unity.py"), issues)
            self.assertIn(("formal_module_missing_from_report", "src/sfm_colmap.py"), issues)
            self.assertEqual(result["candidates"][0]["candidate_id"], "COV-001")
            self.assertEqual(result["candidates"][0]["scope"], "quality")

    def test_pass_path_emits_no_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {module: file_entry(90.0) for module in CoverageStrategy().formal_modules}
            files[r"D:\workspace\3d-recon-pipeline\src\train_3dgs.py"] = file_entry(92.0)
            report = write_coverage(root / "coverage.json", files)

            result = CoverageStrategy().analyze(report)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["finding_count"], 0)
            self.assertEqual(result["candidates"], [])

    def test_missing_and_invalid_report_paths_emit_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = CoverageStrategy()

            missing = strategy.analyze(root / "missing.json")
            self.assertEqual(missing["status"], "missing_report")
            self.assertEqual(missing["candidates"][0]["blocked_by"], ["coverage_report_missing"])

            invalid = root / "invalid.json"
            invalid.write_text(json.dumps({"files": []}), encoding="utf-8")
            result = strategy.write_report(invalid, root / "coverage_strategy_report.json")
            self.assertEqual(result["status"], "invalid_report")
            self.assertTrue((root / "coverage_strategy_report.json").exists())


if __name__ == "__main__":
    unittest.main()
