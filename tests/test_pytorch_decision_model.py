from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from adapters.pytorch_decision_model import (
    build_feature_vector,
    build_training_batch,
    feature_vector_dim,
    load_feedback_records,
    predict_decision_usefulness,
    train_decision_model,
)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def make_record(*, useful: bool, psnr: float, lpips: float, source: str, layer: str) -> dict:
    return {
        "decision_useful": useful,
        "decision": "hold_export",
        "can_proceed": False,
        "requires_human_review": True,
        "human_override": False,
        "wasted_run": False,
        "repeated_problem": not useful,
        "critical_bad_release": False,
        "selected_source_module": source,
        "problem_layer": layer,
        "contract_stage": "train_complete",
        "observed_metrics": {
            "contract_metrics": {
                "psnr": psnr,
                "ssim": 0.85 if useful else 0.70,
                "lpips": lpips,
                "num_gs": 750000 if useful else 1000000,
            }
        },
    }


class PyTorchDecisionModelTests(unittest.TestCase):
    def test_feature_dim_and_unlabeled_filtering(self):
        labeled = make_record(useful=True, psnr=24.0, lpips=0.18, source="MapValidator", layer="parameter")
        unlabeled = dict(labeled)
        unlabeled["decision_useful"] = None

        vector = build_feature_vector(labeled)
        self.assertEqual(len(vector), feature_vector_dim())

        batch = build_training_batch([labeled, unlabeled])
        self.assertEqual(batch.size, 1)
        self.assertEqual(batch.feature_dim, feature_vector_dim())

    def test_train_and_predict_probability(self):
        records = [
            make_record(useful=True, psnr=26.0, lpips=0.12, source="ProductionParamGate", layer="parameter"),
            make_record(useful=True, psnr=25.0, lpips=0.13, source="ProductionParamGate", layer="parameter"),
            make_record(useful=False, psnr=17.0, lpips=0.31, source="MapValidator", layer="framework"),
            make_record(useful=False, psnr=18.0, lpips=0.28, source="MapValidator", layer="framework"),
        ]
        result = train_decision_model(records, epochs=120, learning_rate=5e-3, hidden_dim=16)

        self.assertEqual(result["dataset_size"], 4)
        self.assertGreaterEqual(result["train_accuracy"], 0.75)
        self.assertGreater(result["losses"][0], result["losses"][-1])

        good_score = predict_decision_usefulness(result["model"], records[0])
        bad_score = predict_decision_usefulness(result["model"], records[-1])
        self.assertGreater(good_score, bad_score)
        self.assertGreaterEqual(good_score, 0.0)
        self.assertLessEqual(good_score, 1.0)

    def test_load_feedback_records_from_audit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                root / "run_a" / "train_complete" / "outcome_feedback.json",
                make_record(useful=True, psnr=24.0, lpips=0.15, source="MapValidator", layer="parameter"),
            )
            write_json(
                root / "run_b" / "export_complete" / "outcome_feedback.json",
                make_record(useful=False, psnr=18.0, lpips=0.30, source="PointCloudValidator", layer="data"),
            )
            records = load_feedback_records(root)
            self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
