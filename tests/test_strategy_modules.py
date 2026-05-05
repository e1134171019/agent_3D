from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agents.phase0.map_diagnostics import MapDiagnostics
from agents.phase0.map_validator import MapValidator
from agents.phase0.production_param_gate import ProductionParamGate


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class ProductionParamGateTests(unittest.TestCase):
    def test_profiles_cover_missing_pass_fail_and_quality_recovery_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = ProductionParamGate()
            gate.propose(str(root / "missing_pc.json"), str(root / "missing_val.json"))
            self.assertEqual(gate.sfm_plan["profile_name"], "hold_missing_upstream")
            self.assertEqual(gate.train_plan["profile_name"], "hold_until_sfm_pass")
            self.assertFalse(gate.evaluate()["approved"])

            pc_pass = write_json(root / "pc_pass.json", {"can_proceed_to_3dgs": True})
            gate = ProductionParamGate()
            gate.propose(str(pc_pass), str(root / "missing_val.json"))
            self.assertEqual(gate.train_plan["profile_name"], "train_completion")
            self.assertTrue(gate.evaluate()["approved"])
            self.assertEqual(gate.decision["gate_status"], "rerun_train")

            validation_pass = write_json(root / "val_pass.json", {"overall_pass": True})
            gate = ProductionParamGate()
            gate.propose(str(pc_pass), str(validation_pass))
            self.assertEqual(gate.train_plan["profile_name"], "hold_current_train")
            self.assertFalse(gate.evaluate()["approved"])
            self.assertEqual(gate.decision["gate_status"], "hold_manual_review")

            pc_fail = write_json(
                root / "pc_fail.json",
                {
                    "can_proceed_to_3dgs": False,
                    "points3d_count": 500,
                    "cameras_count": 1,
                    "diagnosis": "sparse",
                },
            )
            gate = ProductionParamGate()
            gate.propose(str(pc_fail), str(root / "missing_val.json"))
            self.assertEqual(gate.sfm_plan["recommended_params"]["max_features"], 16000)
            self.assertEqual(gate.sfm_plan["recommended_params"]["seq_overlap"], 15)
            self.assertTrue(gate.evaluate()["approved"])
            self.assertEqual(gate.decision["gate_status"], "rerun_sfm")

            for action, expected in [
                ("retrain", "quality_recovery"),
                ("investigate", "investigate_then_retrain"),
            ]:
                val = write_json(
                    root / f"val_{action}.json",
                    {
                        "overall_pass": False,
                        "psnr": 17,
                        "ssim": 0.7,
                        "lpips": 0.3,
                        "diagnosis": {"recommended_action": action, "reason": action},
                    },
                )
                gate = ProductionParamGate()
                gate.propose(str(pc_pass), str(val))
                self.assertEqual(gate.train_plan["profile_name"], expected)
                self.assertTrue(gate.evaluate()["approved"])
                result = gate.execute(str(root / f"out_{action}"))
                self.assertEqual(result["status"], "success")



class DiagnosticsAndValidatorTests(unittest.TestCase):
    def test_map_diagnostics_rule_matrix(self):
        diag = MapDiagnostics()
        cases = [
            ((22, 0.9, 0.1, None, None), "quality_acceptable"),
            ((10, 0.7, 0.2, None, None), "insufficient_training"),
            ((17, 0.8, 0.19, {"total_runs": 3}, None), "sparse_gaussians"),
            ((16, 0.7, 0.2, {"total_runs": 3, "psnr_trend": "improving"}, {"steps_completed": 10000}), "improving_insufficient_steps"),
            ((19, 0.79, 0.16, {"total_runs": 6, "psnr_trend": "stable", "ssim_trend": "stable", "lpips_trend": "stable"}, None), "plateau_reached"),
            ((21, 0.82, 0.31, {"total_runs": 3}, None), "lpips_anomaly"),
            ((19, 0.7, 0.2, {"total_runs": 3}, None), "quality_insufficient"),
            ((20, 0.8, 0.15, {"total_runs": 3}, None), "unknown"),
        ]
        for args, expected in cases:
            self.assertEqual(diag.diagnose(*args).diagnosis, expected)

    def test_map_validator_success_and_missing_input_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validator = MapValidator(log_path=str(root / "missing_history.json"))
            self.assertEqual(validator.propose(str(root / "missing_stats.json"))["status"], "failed")
            self.assertFalse(validator.evaluate()["overall_pass"])
            self.assertEqual(validator.execute(str(root / "missing_report.json"))["status"], "error")

            stats = write_json(root / "stats.json", {"psnr": 25.0, "ssim": 0.9, "lpips": 0.05, "iteration": 30000})
            validator = MapValidator(log_path=str(root / "history.json"))
            proposal = validator.propose(str(stats))
            self.assertEqual(proposal["diagnosis_action"], "approve")
            decision = validator.evaluate()
            self.assertTrue(decision["overall_pass"])
            result = validator.execute(str(root / "validation_report.json"))
            self.assertEqual(result["status"], "success")



if __name__ == "__main__":
    unittest.main()

