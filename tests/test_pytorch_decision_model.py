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
    ISSUE_TYPE_VOCAB,
    RUN_ROLE_VOCAB,
    UNITY_RESULT_VOCAB,
    augmented_feature_vector_dim,
    build_augmented_feature_vector,
    build_augmented_training_batch,
    build_backfill_feature_vector,
    build_feature_vector,
    build_training_batch,
    feature_vector_dim,
    load_feedback_records,
    load_jsonl_records,
    predict_augmented_decision_usefulness,
    predict_decision_usefulness,
    train_augmented_decision_model,
    train_decision_model,
)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_jsonl(path: Path, payloads: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for payload in payloads:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
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


def make_backfill_record(*, useful: bool, role: str, issue: str, unity_result: str, psnr: float, lpips: float) -> dict:
    return {
        "run_id": f"run-{role}-{issue}-{unity_result}-{int(useful)}",
        "experiment_family": "mcmc_probe",
        "contract_stage": "train_complete",
        "train_mode": "mcmc",
        "cap_max": 750000,
        "antialiased": True,
        "random_bkgd": False,
        "mcmc_min_opacity": 0.005,
        "mcmc_noise_lr": 500000.0,
        "psnr": psnr,
        "ssim": 0.88 if useful else 0.85,
        "lpips": lpips,
        "num_gs": 750000,
        "unity_result": unity_result,
        "run_useful": useful,
        "role": role,
        "issue_type": issue,
        "failure_reason": "reason",
        "next_recommendation": "next",
        "teacher_labels": {
            "run_useful": useful,
            "role": role,
            "issue_type": issue,
            "unity_result": unity_result,
            "confidence": 0.82,
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
        self.assertEqual(feature_vector_dim(), 28)

    def test_augmented_feature_vector_with_mock_teacher(self):
        record = make_record(useful=True, psnr=24.0, lpips=0.18, source="MapValidator", layer="parameter")
        teacher = {
            "run_useful": False,
            "role": "unity_candidate",
            "issue_type": "unity_render",
            "unity_result": "visual_fail",
            "confidence": 0.85,
        }

        vector = build_augmented_feature_vector(record, teacher)
        self.assertEqual(len(vector), augmented_feature_vector_dim())
        self.assertEqual(augmented_feature_vector_dim(), 44)
        role_end = len(RUN_ROLE_VOCAB)
        issue_end = role_end + len(ISSUE_TYPE_VOCAB)
        unity_end = issue_end + len(UNITY_RESULT_VOCAB)
        teacher_slice = vector[-unity_end:]
        self.assertEqual(sum(teacher_slice[:role_end]), 1.0)
        self.assertEqual(sum(teacher_slice[role_end:issue_end]), 1.0)
        self.assertEqual(sum(teacher_slice[issue_end:unity_end]), 1.0)

    def test_backfill_issue_type_projects_into_problem_layer_space(self):
        record = make_backfill_record(
            useful=False,
            role="failed_probe",
            issue="unity_render",
            unity_result="visual_fail",
            psnr=0.0,
            lpips=0.0,
        )
        vector = build_backfill_feature_vector(record)
        base_problem_layer_start = 10 + 6 + 4
        problem_layer_slice = vector[base_problem_layer_start:base_problem_layer_start + 4]
        self.assertEqual(problem_layer_slice, [0.0, 0.0, 1.0, 0.0])
        runtime_bools = vector[4:10]
        self.assertEqual(runtime_bools, [0.0, 1.0, 0.0, 1.0, 0.0, 0.0])

    def test_augmented_feature_vector_unknown_teacher_labels_fallback(self):
        record = make_record(useful=False, psnr=18.0, lpips=0.31, source="MapValidator", layer="framework")
        teacher = {
            "run_useful": None,
            "role": "nonexistent",
            "issue_type": "nonexistent",
            "unity_result": "nonexistent",
            "confidence": "bad",
        }

        vector = build_augmented_feature_vector(record, teacher)
        self.assertEqual(len(vector), augmented_feature_vector_dim())
        self.assertEqual(augmented_feature_vector_dim(), 44)

    def test_backfill_feature_vector_ignores_scaffold_probe_context(self):
        record = make_backfill_record(
            useful=False,
            role="failed_probe",
            issue="framework",
            unity_result="not_tested",
            psnr=0.0,
            lpips=0.0,
        )
        plain_vector = build_backfill_feature_vector(record)
        record["probe_context"] = {
            "framework_name": "scaffold_gs",
            "probe_status": "trained",
        }
        contextual_vector = build_backfill_feature_vector(record)
        self.assertEqual(len(contextual_vector), feature_vector_dim())
        self.assertEqual(plain_vector, contextual_vector)

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

    def test_build_augmented_training_batch_from_backfill_records(self):
        records = [
            make_backfill_record(useful=True, role="benchmark", issue="framework", unity_result="visual_fail", psnr=26.1, lpips=0.19),
            make_backfill_record(useful=False, role="failed_probe", issue="parameter", unity_result="not_tested", psnr=24.0, lpips=0.23),
        ]
        batch = build_augmented_training_batch(records)
        self.assertEqual(batch.size, 2)
        self.assertEqual(batch.feature_dim, augmented_feature_vector_dim())
        self.assertEqual([round(x, 2) for x in batch.sample_weights.tolist()], [0.82, 0.82])
        self.assertEqual(batch.features.shape[1], feature_vector_dim() + 4 + 7 + 5)

    def test_train_augmented_model_and_predict(self):
        records = [
            make_backfill_record(useful=True, role="benchmark", issue="framework", unity_result="visual_fail", psnr=26.15, lpips=0.19187),
            make_backfill_record(useful=True, role="unity_candidate", issue="unity_render", unity_result="candidate", psnr=26.15, lpips=0.19529),
            make_backfill_record(useful=False, role="failed_probe", issue="parameter", unity_result="not_tested", psnr=24.10, lpips=0.2280),
            make_backfill_record(useful=False, role="failed_probe", issue="export", unity_result="visual_fail", psnr=0.0, lpips=0.0),
        ]
        result = train_augmented_decision_model(records, epochs=180, learning_rate=4e-3, hidden_dim=16)
        self.assertEqual(result["dataset_size"], 4)
        self.assertGreaterEqual(result["train_accuracy"], 0.75)
        self.assertGreater(result["losses"][0], result["losses"][-1])

        useful_score = predict_augmented_decision_usefulness(result["model"], records[0])
        failed_score = predict_augmented_decision_usefulness(result["model"], records[-1])
        self.assertGreater(useful_score, failed_score)

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

    def test_load_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            payloads = [make_backfill_record(useful=True, role="benchmark", issue="framework", unity_result="visual_fail", psnr=26.0, lpips=0.19)]
            write_jsonl(path, payloads)
            loaded = load_jsonl_records(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["role"], "benchmark")


if __name__ == "__main__":
    unittest.main()
