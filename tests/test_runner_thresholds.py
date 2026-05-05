from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from adapters.adaptive_threshold import AdaptiveThreshold
from agents.phase0.pointcloud_validator import PointCloudValidator, validate_pointcloud
from src.phase0_runner import Phase0Runner


def write_json(path: Path, payload: dict | list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class Phase0RunnerPathTests(unittest.TestCase):
    def test_verify_execute_and_watch_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prod = root / "prod"
            events = prod / "agent_events"
            out = root / "out"
            decisions = root / "decisions"
            unity = root / "unity"
            events.mkdir(parents=True)
            unity.mkdir()
            contract = write_json(events / "latest_export_complete.json", {"run_id": "r1", "stage": "export_complete"})

            runner = Phase0Runner(prod, events, out, decisions, unity)
            runner.verify_system()

            with mock.patch("src.coordinator.Phase0Coordinator") as coordinator_cls:
                coordinator_cls.return_value.run.return_value = {"output_root": str(out)}
                self.assertEqual(runner.execute_single(contract)["output_root"], str(out))
                coordinator_cls.assert_called_once()

            with self.assertRaises(SystemExit):
                runner.execute_single(root / "missing.json")

            empty_runner = Phase0Runner(prod, root / "empty_events", out, decisions, unity)
            with self.assertRaises(SystemExit):
                empty_runner.execute_single()

            with mock.patch.object(runner, "_list_latest_contracts", side_effect=[[], KeyboardInterrupt]):
                with mock.patch("src.phase0_runner.time.sleep", return_value=None):
                    runner.watch_mode(poll_seconds=0.01)

            with mock.patch.object(runner, "_list_latest_contracts", side_effect=[[contract], KeyboardInterrupt]):
                with mock.patch.object(runner, "execute_single", side_effect=RuntimeError("boom")):
                    with mock.patch("src.phase0_runner.time.sleep", return_value=None):
                        runner.watch_mode(poll_seconds=0.01)

            missing_runner = Phase0Runner(root / "missing_prod", root / "missing_events", out, decisions, root / "missing_unity")
            missing_runner.verify_system()


class PointCloudValidatorBranchTests(unittest.TestCase):
    def test_invalid_raw_failure_and_write_error_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validator = PointCloudValidator(verbose=True)

            invalid = root / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            self.assertIn("無法解析 JSON", validator.validate(invalid)["diagnosis"])

            missing_fields = write_json(root / "missing_fields.json", {"cameras_count": 2})
            self.assertIn("缺失必要欄位", validator.validate(missing_fields)["diagnosis"])

            raw_fail = write_json(
                root / "raw_fail.json",
                {"cameras_count": 1, "points3d_count": 10, "avg_reprojection_error": 4.5},
            )
            fail_report = validator.validate(raw_fail)
            self.assertFalse(fail_report["can_proceed_to_3dgs"])
            self.assertIn("相機數量不足", fail_report["diagnosis"])

            raw_pass = write_json(
                root / "raw_pass.json",
                {"cameras_count": 8, "points3d_count": 80000, "avg_reprojection_error": 1.0},
            )
            self.assertTrue(validate_pointcloud(raw_pass, root / "report.json", verbose=True))
            self.assertTrue(validator.validate_and_report(raw_pass, root))


class AdaptiveThresholdBranchTests(unittest.TestCase):
    def test_history_formats_threshold_bounds_trends_and_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(AdaptiveThreshold(str(root / "missing.log")).history, [])

            empty = root / "empty.log"
            empty.write_text("", encoding="utf-8")
            self.assertEqual(AdaptiveThreshold(str(empty)).history, [])

            dict_log = write_json(root / "dict.json", {"overall_pass": True, "metrics": {"psnr": 20}})
            self.assertEqual(len(AdaptiveThreshold(str(dict_log)).history), 1)

            lines = root / "lines.jsonl"
            lines.write_text(
                "\n".join(
                    [
                        json.dumps({"overall_pass": True, "metrics": {"psnr": 20, "ssim": 0.8, "lpips": 0.2}}),
                        json.dumps({"overall_pass": True, "metrics": {"psnr": 20.005, "ssim": 0.8, "lpips": 0.15}}),
                        json.dumps({"overall_pass": True, "metrics": {"psnr": 20.01, "ssim": 0.8, "lpips": 0.10}}),
                        json.dumps({"action": "approved", "metrics": {"psnr": 20.015, "ssim": 0.8, "lpips": 0.05}}),
                    ]
                ),
                encoding="utf-8",
            )
            threshold = AdaptiveThreshold(str(lines), window=4)
            self.assertEqual(threshold.get_trend("psnr"), "stable")
            self.assertEqual(threshold.get_trend("lpips"), "improving")
            self.assertEqual(threshold.get_trend("missing"), None)
            self.assertEqual(threshold.recommend_action("psnr", 30, 20), "approve")
            self.assertIn(threshold.recommend_action("psnr", 1, 20), {"retrain", "investigate"})

            invalid = root / "invalid.log"
            invalid.write_text("{\nnot-json\n", encoding="utf-8")
            self.assertEqual(AdaptiveThreshold(str(invalid)).history, [])

            high = write_json(
                root / "high.json",
                [
                    {"overall_pass": True, "metrics": {"psnr": 100}},
                    {"overall_pass": True, "metrics": {"psnr": 120}},
                    {"overall_pass": True, "metrics": {"psnr": 140}},
                ],
            )
            self.assertLessEqual(AdaptiveThreshold(str(high)).get_threshold("psnr", 20, max_threshold=25), 25)

    def test_prefers_outcome_feedback_audit_root_before_legacy_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            write_json(
                root / "run1" / "train_complete" / "outcome_feedback.json",
                {
                    "recorded_at": "2026-05-01T00:00:00",
                    "outcome_status": "held_for_review",
                    "decision_useful": True,
                    "wasted_run": False,
                    "critical_bad_release": False,
                    "observed_metrics": {
                        "contract_metrics": {"psnr": 21.0, "ssim": 0.81, "lpips": 0.14}
                    },
                },
            )
            write_json(
                root / "run2" / "train_complete" / "outcome_feedback.json",
                {
                    "recorded_at": "2026-05-02T00:00:00",
                    "outcome_status": "held_for_review",
                    "decision_useful": True,
                    "wasted_run": False,
                    "critical_bad_release": False,
                    "observed_metrics": {
                        "contract_metrics": {"psnr": 22.0, "ssim": 0.82, "lpips": 0.13}
                    },
                },
            )
            write_json(
                root / "run3" / "train_complete" / "outcome_feedback.json",
                {
                    "recorded_at": "2026-05-03T00:00:00",
                    "outcome_status": "held_for_review",
                    "decision_useful": False,
                    "wasted_run": True,
                    "critical_bad_release": False,
                    "observed_metrics": {
                        "contract_metrics": {"psnr": 10.0, "ssim": 0.40, "lpips": 0.50}
                    },
                },
            )

            threshold = AdaptiveThreshold(str(root / "phase0_decisions.log"), window=5)
            self.assertEqual(threshold.history_source, "outcome_feedback")
            self.assertEqual(len(threshold.history), 3)
            self.assertGreater(threshold.get_threshold("psnr", 20.0), 20.0)
            self.assertEqual(threshold.get_trend("psnr"), None)
            self.assertEqual(threshold.learning_curve.get("overall", {}).get("decision_count"), 3)



if __name__ == "__main__":
    unittest.main()

