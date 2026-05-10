from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

import run_phase0
from adapters.adaptive_threshold import AdaptiveThreshold
from agents.phase0.pointcloud_validator import PointCloudValidator
from src.arbiter import Phase0Arbiter
from src.candidate_pool import Phase0CandidatePoolBuilder, ProblemLayerAnalyzer
from src.contract_io import (
    ContractValidationError,
    normalize_stage_contract,
    read_json_records,
    validate_arbiter_decision,
    validate_candidate_pool,
    validate_current_state,
    validate_outcome_feedback,
    validate_shared_decision,
)
from src.current_state import Phase0CurrentStateBuilder
from src.outcome_feedback import OutcomeFeedbackHistory, Phase0OutcomeFeedbackBuilder
from src.phase0_runner import Phase0Runner
from src.shared_decision_mapper import Phase0SharedDecisionMapper


class AgentCoreCoverageTests(unittest.TestCase):
    def test_problem_layer_analyzer_is_single_source_for_resolution_and_aggregation(self):
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"problem_layer": "parameter"}, {"reason": "pointcloud text ignored"}),
            "parameter",
        )
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"stage": "PointCloudValidator"}, {"reason": "camera coverage weak"}),
            "data",
        )
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"stage": "MapValidator"}, {"decision_note": "LPIPS threshold failed"}),
            "parameter",
        )
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"stage": "train_complete"}, {"reason": "needs human review"}),
            "framework",
        )
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"stage": "MapValidator"}, {"reason": "training_stats_missing"}),
            "parameter",
        )
        self.assertEqual(
            ProblemLayerAnalyzer.resolve({"stage": "StrategyRouter"}, {"reason": "switch MCMC strategy"}),
            "framework",
        )

        aggregate = ProblemLayerAnalyzer.aggregate(
            [
                {"candidate_id": "A", "problem_layer": "parameter"},
                {"candidate_id": "B", "problem_layer": "parameter"},
                {"candidate_id": "C", "problem_layer": "data"},
            ]
        )
        self.assertEqual(aggregate["dominant_layer"], "parameter")
        self.assertEqual(aggregate["layer_counts"]["parameter"], 2)
        self.assertEqual(aggregate["candidate_ids"]["parameter"], ["A", "B"])

    def test_contract_io_normalizes_stage_contract_and_history_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records.jsonl"
            records.write_text(
                "\n".join(
                    [
                        json.dumps({"overall_pass": True, "metrics": {"psnr": 20}}),
                        json.dumps({"action": "approved", "metrics": {"psnr": 22}}),
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(len(read_json_records(records)), 2)

            normalized = normalize_stage_contract(
                {
                    "schema_version": 1,
                    "timestamp": "2026-04-26T00:00:00",
                    "run_id": "run1",
                    "run_root": str(root),
                    "stage": "train_complete",
                    "status": "completed",
                    "artifacts": None,
                    "metrics": {"lpips": 0.2},
                    "params": {"train_mode": "mcmc"},
                },
                source_path="contract.json",
            )
            self.assertEqual(normalized["artifacts"], {})

            with self.assertRaises(ContractValidationError):
                normalize_stage_contract({"stage": "train_complete"}, source_path="bad.json")

    def test_run_phase0_main_delegates_verify_and_single_execution(self):
        with mock.patch.object(run_phase0, "Phase0Runner") as runner_cls:
            runner = runner_cls.return_value
            with mock.patch.object(sys, "argv", ["run_phase0.py", "--verify"]):
                self.assertEqual(run_phase0.main(), 0)
            runner.verify_system.assert_called_once()

        with mock.patch.object(run_phase0, "Phase0Runner") as runner_cls:
            runner = runner_cls.return_value
            with mock.patch.object(sys, "argv", ["run_phase0.py", "--contract", "contract.json"]):
                self.assertEqual(run_phase0.main(), 0)
            runner.execute_single.assert_called_once_with(contract_path="contract.json")

    def test_candidate_pool_uses_feedback_history_as_ranking_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior_feedback_path = root / "old_run" / "train_complete" / "outcome_feedback.json"
            prior_feedback_path.parent.mkdir(parents=True, exist_ok=True)
            prior_feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "feedback_id": "old-feedback",
                        "decision_ref": "arbiter_decision.json",
                        "run_id": "old-run",
                        "outcome_status": "accepted",
                        "observed_metrics": {},
                        "observed_artifacts": {},
                        "drift_vs_expectation": [],
                        "lessons": [],
                        "update_targets": [],
                        "recorded_at": "2026-04-29T00:00:00",
                        "selected_candidate_id": "VAL-001",
                        "selected_source_module": "validation",
                        "decision": "proceed_to_export",
                        "can_proceed": True,
                        "requires_human_review": False,
                        "decision_useful": True,
                        "problem_layer": "parameter",
                    }
                ),
                encoding="utf-8",
            )

            output_path = root / "new_run" / "train_complete" / "candidate_pool.json"
            payload = Phase0CandidatePoolBuilder("run1", "train_complete").build(
                decision_log=[
                    {
                        "stage": "recovery",
                        "proposal_id": "REC-001",
                        "proposal_text": "recover",
                        "evaluation": {"confidence": "0.8"},
                        "action": "approved",
                        "action_reason": "fallback",
                    },
                    {
                        "stage": "validation",
                        "proposal_id": "VAL-001",
                        "proposal_text": "validate pointcloud quality with explicit parameter layer",
                        "problem_layer": "parameter",
                        "evaluation": {"confidence": "0.7", "decision_note": "ok"},
                        "action": "approved",
                        "action_reason": "metrics acceptable",
                    },
                    {
                        "stage": "pointcloud_validator",
                        "proposal_id": "PC-001",
                        "proposal_text": "check pointcloud",
                        "evaluation": {"confidence": "0.4"},
                        "action": "approved",
                        "action_reason": "camera coverage weak",
                    },
                ],
                output_path=output_path,
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(payload["candidate_count"], 3)
            self.assertEqual(payload["candidates"][0]["source_module"], "validation")
            self.assertEqual(payload["candidates"][0]["history_signal"]["accepted_runs"], 1)
            self.assertEqual(payload["candidates"][0]["history_signal"]["accepted_rate"], 1.0)
            self.assertEqual(payload["candidates"][0]["history_signal"]["effectiveness_rate"], 1.0)
            self.assertEqual(payload["candidates"][0]["history_signal"]["decision_useful_runs"], 1)
            self.assertEqual(payload["candidates"][0]["problem_layer"], "parameter")
            self.assertEqual(payload["candidates"][1]["problem_layer"], "framework")
            self.assertEqual(payload["candidates"][2]["problem_layer"], "data")
            self.assertGreater(payload["candidates"][0]["rank_score"], payload["candidates"][1]["rank_score"])

            history = OutcomeFeedbackHistory(root).summarize_by_source_module()
            self.assertEqual(history["validation"]["accepted_runs"], 1)

    def test_candidate_pool_penalizes_repeat_error_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good_feedback_path = root / "good_run" / "train_complete" / "outcome_feedback.json"
            bad_feedback_path = root / "bad_run" / "train_complete" / "outcome_feedback.json"
            good_feedback_path.parent.mkdir(parents=True, exist_ok=True)
            bad_feedback_path.parent.mkdir(parents=True, exist_ok=True)

            good_feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "feedback_id": "good-feedback",
                        "decision_ref": "arbiter_decision.json",
                        "run_id": "good-run",
                        "outcome_status": "accepted",
                        "observed_metrics": {},
                        "observed_artifacts": {},
                        "drift_vs_expectation": [],
                        "lessons": [],
                        "update_targets": [],
                        "recorded_at": "2026-04-01T00:00:00",
                        "selected_candidate_id": "GOOD-001",
                        "selected_source_module": "GoodModule",
                        "decision": "proceed",
                        "can_proceed": True,
                        "requires_human_review": False,
                        "decision_useful": True,
                        "problem_layer": "parameter",
                        "repeated_problem": False,
                    }
                ),
                encoding="utf-8",
            )
            bad_feedback_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "feedback_id": "bad-feedback",
                        "decision_ref": "arbiter_decision.json",
                        "run_id": "bad-run",
                        "outcome_status": "accepted",
                        "observed_metrics": {},
                        "observed_artifacts": {},
                        "drift_vs_expectation": [],
                        "lessons": [],
                        "update_targets": [],
                        "recorded_at": "2026-04-02T00:00:00",
                        "selected_candidate_id": "BAD-001",
                        "selected_source_module": "BadModule",
                        "decision": "proceed",
                        "can_proceed": True,
                        "requires_human_review": False,
                        "decision_useful": True,
                        "problem_layer": "parameter",
                        "repeated_problem": True,
                    }
                ),
                encoding="utf-8",
            )

            output_path = root / "new_run" / "train_complete" / "candidate_pool.json"
            payload = Phase0CandidatePoolBuilder("run1", "train_complete").build(
                decision_log=[
                    {
                        "stage": "GoodModule",
                        "proposal_id": "GOOD-001",
                        "proposal_text": "good candidate",
                        "evaluation": {"confidence": "0.6", "decision_note": "good"},
                        "action": "approved",
                        "action_reason": "stable",
                    },
                    {
                        "stage": "BadModule",
                        "proposal_id": "BAD-001",
                        "proposal_text": "bad candidate",
                        "evaluation": {"confidence": "1.0", "decision_note": "bad"},
                        "action": "approved",
                        "action_reason": "stable",
                    },
                ],
                output_path=output_path,
            )

            self.assertEqual(payload["candidate_count"], 2)
            self.assertGreater(payload["candidates"][0]["rank_score"], payload["candidates"][1]["rank_score"])
            self.assertEqual(payload["candidates"][0]["source_module"], "GoodModule")
            self.assertEqual(payload["candidates"][1]["source_module"], "BadModule")

    def test_core_schema_validators_reject_malformed_decision_artifacts(self):
        with self.assertRaises(ContractValidationError):
            validate_candidate_pool(
                {
                    "schema_version": 1,
                    "timestamp": "now",
                    "run_id": "run1",
                    "contract_stage": "train_complete",
                    "candidate_count": 1,
                    "candidates": [],
                },
                source_path="candidate_pool.json",
            )

        with self.assertRaises(ContractValidationError):
            validate_current_state(
                {
                    "schema_version": 1,
                    "state_id": "state1",
                    "phase": "phase0",
                    "active_pack": "map_building",
                    "current_best": "best",
                    "next_focus": "next",
                    "allowed_actions": "review",
                    "blocked_actions": [],
                    "blacklist": [],
                    "source_docs": [],
                    "updated_at": "now",
                },
                source_path="current_state.json",
            )

        with self.assertRaises(ContractValidationError):
            validate_arbiter_decision(
                {
                    "schema_version": 1,
                    "decision_id": "decision1",
                    "state_ref": "state.json",
                    "event_ref": "event.json",
                    "selected_candidate_id": "VAL-001",
                    "rejected_candidate_ids": [],
                    "decision": "hold",
                    "reason": "bad",
                    "next_action": {},
                    "can_proceed": "false",
                    "requires_human_review": True,
                    "written_at": "now",
                },
                source_path="arbiter_decision.json",
            )

        with self.assertRaises(ContractValidationError):
            validate_shared_decision(
                {
                    "schema_version": 1,
                    "timestamp": "now",
                    "run_id": "run1",
                    "source_contract": "event.json",
                    "source_stage": "train_complete",
                    "source_status": "completed",
                    "run_root": "root",
                    "decision_stage": "train",
                    "decision_gate": "gate_2_3",
                    "decision": "hold_export",
                    "can_proceed": False,
                    "recommendation": "hold",
                    "next_steps": [],
                    "metrics": {},
                    "arbiter": {},
                    "state": {},
                    "reports": {},
                },
                source_path="latest_train_decision.json",
            )

        with self.assertRaises(ContractValidationError):
            validate_outcome_feedback(
                {
                    "schema_version": 1,
                    "feedback_id": "feedback1",
                    "decision_ref": "arbiter_decision.json",
                    "run_id": "run1",
                    "outcome_status": "held_for_review",
                    "observed_metrics": {},
                    "observed_artifacts": {},
                    "drift_vs_expectation": [],
                    "lessons": "not a list",
                    "update_targets": [],
                    "recorded_at": "now",
                },
                source_path="outcome_feedback.json",
            )

    def test_current_state_maps_stage_to_allowed_and_blocked_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "current_state.json"
            payload = Phase0CurrentStateBuilder(
                run_id="run1",
                contract_stage="export_complete",
                contract_status="completed",
                source_contract="contract.json",
                run_root="run_root",
            ).build(
                report_data={"recommendation": "export ok", "next_steps": ["close"]},
                candidate_pool={
                    "candidates": [                        {"candidate_id": "VAL-001", "source_module": "MapValidator", "problem_layer": "parameter"},
                        {"candidate_id": "VAL-002", "source_module": "ProductionParamGate", "problem_layer": "parameter"},
                        {
                            "candidate_id": "SKIP-001",
                            "source_module": "LegacySkippedStage",
                            "problem_layer": "parameter",
                            "blocked_by": ["missing_artifact"],
                            "evidence": {"action": "skipped"},
                        },
                    ]
                },
                output_path=output_path,
            )

            self.assertEqual(payload["active_pack"], "map_building")
            self.assertEqual(payload["next_focus"], "close")
            self.assertIn("close_phase", payload["allowed_actions"])
            self.assertIn("proceed_to_train", payload["blocked_actions"])
            self.assertEqual(payload["context"]["candidate_count"], 3)
            self.assertEqual(payload["context"]["problem_layer_signal"]["dominant_layer"], "parameter")
            self.assertEqual(payload["context"]["problem_layer_signal"]["layer_counts"]["parameter"], 3)
            self.assertEqual(payload["context"]["problem_layer_signal"]["ignored_skipped_count"], 1)
            self.assertEqual(payload["context"]["problem_layer_signal"]["source"], "all_candidates")
            self.assertEqual(payload["context"]["problem_layer_signal"]["ignored_support_count"], 0)

    def test_arbiter_uses_problem_layer_signal_for_hold_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run1" / "export_complete"
            out.mkdir(parents=True, exist_ok=True)
            candidates = {
                "candidates": [
                    {"candidate_id": "VAL-001", "source_module": "MapValidator", "problem_layer": "parameter", "rank_score": 0.61},
                    {"candidate_id": "PC-001", "problem_layer": "data", "rank_score": 0.93},
                    {"candidate_id": "REC-001", "problem_layer": "framework", "rank_score": 0.52},
                    {"candidate_id": "PPG-001", "source_module": "ProductionParamGate", "problem_layer": "parameter", "rank_score": 0.91},
                ]
            }

            train_data = Phase0Arbiter("run1", "train_complete", "c.json", "root").decide(
                current_state={"active_pack": "map_building", "context": {"problem_layer_signal": {"dominant_layer": "data"}}},
                report_data={"validation_ready": False, "validation_pass": False, "recommendation": "bad geometry"},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "train_data.json",
                history_signal={"total_decisions": 4, "ai_exit_readiness_trend": {"direction": "improving"}},
            )
            train_param = Phase0Arbiter("run1", "train_complete", "c.json", "root").decide(
                current_state={"active_pack": "map_building", "context": {"problem_layer_signal": {"dominant_layer": "parameter"}}},
                report_data={"validation_ready": True, "validation_pass": False, "recommendation": "quality issue"},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "train_param.json",
            )
            export_framework = Phase0Arbiter("run1", "export_complete", "c.json", "root").decide(
                current_state={"active_pack": "map_building", "context": {"problem_layer_signal": {"dominant_layer": "framework"}}},
                report_data={"import_success": False, "recommendation": "integration unstable"},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "export_framework.json",
            )

            self.assertEqual(train_data["decision"], "hold_export")
            self.assertEqual(train_data["selected_candidate_id"], "PC-001")
            self.assertEqual(train_data["next_action"]["type"], "recover_upstream")
            self.assertIn("dominant_problem_layer=data", train_data["reason"])
            self.assertEqual(train_data["decision_context"]["history_signal"]["total_decisions"], 4)
            self.assertEqual(train_data["decision_context"]["history_signal"]["ai_exit_readiness_trend"]["direction"], "improving")

            self.assertEqual(train_param["selected_candidate_id"], "PPG-001")
            self.assertEqual(train_param["next_action"]["type"], "review_training")
            self.assertIn("dominant_problem_layer=parameter", train_param["reason"])

            self.assertEqual(export_framework["decision"], "hold_phase_close")
            self.assertEqual(export_framework["selected_candidate_id"], "REC-001")
            self.assertEqual(export_framework["next_action"]["type"], "switch_strategy")

    def test_arbiter_uses_rank_score_within_same_problem_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            candidates = {
                "candidates": [
                    {"candidate_id": "VAL-001", "source_module": "MapValidator", "problem_layer": "parameter", "rank_score": 0.62},
                    {"candidate_id": "PPG-001", "source_module": "ProductionParamGate", "problem_layer": "parameter", "rank_score": 0.89},
                    {"candidate_id": "REC-001", "source_module": "Recovery", "problem_layer": "framework", "rank_score": 0.95},
                ]
            }

            decision = Phase0Arbiter("run1", "train_complete", "c.json", "root").decide(
                current_state={"active_pack": "map_building", "context": {"problem_layer_signal": {"dominant_layer": "parameter"}}},
                report_data={"validation_ready": True, "validation_pass": False, "recommendation": "quality issue"},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "ranked_train_hold.json",
            )

            self.assertEqual(decision["decision"], "hold_export")
            self.assertEqual(decision["selected_candidate_id"], "PPG-001")
            self.assertEqual(decision["next_action"]["type"], "review_training")

    def test_arbiter_decides_sfm_train_export_and_unknown_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            candidates = {"candidates": [{"candidate_id": "A"}, {"candidate_id": "B"}]}
            state = {"active_pack": "map_building"}

            sfm = Phase0Arbiter("run1", "sfm_complete", "c.json", "root").decide(
                current_state=state,
                report_data={"pointcloud_pass": True, "recommendation": "go"},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "sfm.json",
            )
            train = Phase0Arbiter("run1", "train_complete", "c.json", "root").decide(
                current_state=state,
                report_data={"validation_ready": False, "validation_pass": False},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "train.json",
            )
            export = Phase0Arbiter("run1", "export_complete", "c.json", "root").decide(
                current_state=state,
                report_data={"import_success": True},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "export.json",
            )
            unknown = Phase0Arbiter("run1", "custom", "c.json", "root").decide(
                current_state=state,
                report_data={"validation_pass": False},
                candidate_pool=candidates,
                state_ref="state.json",
                output_path=out / "unknown.json",
            )

            self.assertEqual(sfm["decision"], "proceed_to_train")
            self.assertIn("written_at", sfm)
            self.assertEqual(train["decision"], "hold_export")
            self.assertTrue(train["requires_human_review"])
            self.assertEqual(export["decision"], "export_verified")
            self.assertEqual(unknown["selected_candidate_id"], "A")

    def test_shared_decision_mapper_outputs_production_schema(self):
        payload = Phase0SharedDecisionMapper(
            run_id="run1",
            source_contract="contract.json",
            source_stage="train_complete",
            source_status="completed",
            run_root="root",
            metrics={"lpips": 0.2},
        ).build(
            report_data={
                "recommendation": "hold",
                "next_steps": ["review"],
                "validation_ready": True,
                "validation_pass": False,
                "train_profile": "mcmc",
            },
            arbiter_decision={
                "decision_stage": "train",
                "decision": "hold_export",
                "can_proceed": False,
                "selected_candidate_id": "VAL-001",
                "requires_human_review": True,
                "next_action": {"type": "review_training"},
            },
            reports={"phase0_report_json": "report.json"},
        )

        self.assertEqual(payload["decision_gate"], "gate_2_3")
        self.assertFalse(payload["can_proceed"])
        self.assertEqual(payload["profiles"]["train"], "mcmc")
        self.assertEqual(payload["state"]["validation_ready"], True)

    def test_outcome_feedback_records_accepted_and_held_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run1" / "export_complete"
            out.mkdir(parents=True, exist_ok=True)
            builder = Phase0OutcomeFeedbackBuilder(
                run_id="run1",
                contract_stage="export_complete",
                contract_status="completed",
                contract_path="contract.json",
                run_root="root",
                metrics={"num_splats": 750000},
                artifacts={"ply_file": "model.ply"},
            )
            accepted = builder.build(
                report_data={"import_success": True, "recommendation": "close", "next_steps": ["done"]},
                candidate_pool={
                    "candidate_count": 1,
                    "candidates": [{"candidate_id": "VAL-001", "source_module": "MapValidator", "problem_layer": "parameter"}],
                },
                current_state={"active_pack": "map_building", "context": {"problem_layer_signal": {"dominant_layer": "framework"}}},
                arbiter_decision={
                    "can_proceed": True,
                    "next_action": {"type": "close_phase"},
                    "reason": "ok",
                    "selected_candidate_id": "VAL-001",
                    "decision": "export_verified",
                },
                shared_decision_path="latest_export_decision.json",
                output_path=out / "outcome_feedback.json",
            )
            held = builder.build(
                report_data={},
                candidate_pool={"candidate_count": 2, "candidates": []},
                current_state={},
                arbiter_decision={"can_proceed": False, "requires_human_review": True},
                shared_decision_path="latest_export_decision.json",
                output_path=Path(tmp) / "run2" / "export_complete" / "outcome_feedback.json",
            )
            held_gate = builder.build(
                report_data={"import_success": False},
                candidate_pool={"candidate_count": 1, "candidates": []},
                current_state={},
                arbiter_decision={
                    "can_proceed": False,
                    "requires_human_review": True,
                    "decision": "hold_phase_close",
                },
                shared_decision_path="latest_export_decision.json",
                output_path=Path(tmp) / "run3" / "export_complete" / "outcome_feedback.json",
            )

            self.assertEqual(accepted["outcome_status"], "accepted")
            self.assertIn("experiment_history", accepted["update_targets"])
            self.assertEqual(accepted["selected_source_module"], "MapValidator")
            self.assertEqual(accepted["problem_layer"], "parameter")
            self.assertEqual(accepted["decision"], "export_verified")
            self.assertIs(accepted["decision_useful"], True)
            self.assertIn("learning_curve", accepted["update_targets"])
            self.assertIn("outcome_label", accepted)
            self.assertGreater(accepted["token_cost_estimate"], 0)
            self.assertEqual(held["outcome_status"], "held_for_review")
            self.assertIsNone(held["decision_useful"])
            self.assertIs(held_gate["decision_useful"], True)
            self.assertIn("human_label", held["update_targets"])
            self.assertEqual(held["lessons"], ["2 candidates evaluated"])
            history = OutcomeFeedbackHistory(Path(tmp))
            curve_path = Path(tmp) / "learning_curve.json"
            curve = history.write_learning_curve(curve_path)
            self.assertTrue(curve_path.exists())
            self.assertEqual(curve["total_decisions"], 3)
            self.assertEqual(curve["overall"]["labeled_decision_count"], 2)
            self.assertIn("ai_exit_readiness_trend", curve)
            self.assertEqual(curve["ai_exit_readiness_trend"]["window_size"], 3)
            self.assertFalse(curve["ai_exit_readiness"]["ready_for_ai_observer_mode"])

            labeled = history.apply_label(
                Path(tmp) / "run2" / "export_complete" / "outcome_feedback.json",
                decision_useful=False,
                metrics_improved=False,
                problem_layer_correct=True,
                human_override=True,
                wasted_run=True,
                repeated_problem=True,
                critical_bad_release=False,
                label_source="unit_test",
                label_note="manual review rejected this decision",
            )
            self.assertEqual(labeled["label_status"], "human_labeled")
            self.assertFalse(labeled["decision_useful"])
            self.assertTrue(labeled["outcome_label"]["human_override"])
            curve = history.write_learning_curve(curve_path)
            self.assertEqual(curve["overall"]["labeled_decision_count"], 3)
            self.assertEqual(curve["overall"]["recommendation_success_rate"], 0.6667)
            self.assertEqual(curve["overall"]["human_override_rate"], 0.3333)
            self.assertEqual(curve["overall"]["repeat_error_rate"], 0.3333)

    def test_phase0_runner_reads_json_and_picks_latest_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events"
            events.mkdir()
            older = events / "latest_sfm_complete.json"
            newer = events / "latest_train_complete.json"
            older.write_text(json.dumps({"stage": "sfm_complete"}), encoding="utf-8")
            newer.write_text(json.dumps({"stage": "train_complete"}), encoding="utf-8-sig")

            runner = Phase0Runner(
                production_root=root,
                events_root=events,
                output_root=root / "out",
                decisions_root=root / "decisions",
                unity_project=root / "unity",
            )

            self.assertEqual(runner._read_json(newer)["stage"], "train_complete")
            self.assertEqual(runner._find_latest_contract(), newer)

    def test_pointcloud_validator_handles_missing_upstream_and_raw_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validator = PointCloudValidator()

            missing = validator.validate(root / "missing.json")
            self.assertFalse(missing["can_proceed_to_3dgs"])

            upstream = root / "upstream.json"
            upstream.write_text(
                json.dumps({"can_proceed_to_3dgs": True, "points3d_count": 60000}),
                encoding="utf-8",
            )
            self.assertTrue(validator.validate(upstream)["can_proceed_to_3dgs"])

            raw = root / "raw.json"
            raw.write_text(
                json.dumps(
                    {
                        "cameras_count": 8,
                        "points3d_count": 70000,
                        "avg_reprojection_error": 1.2,
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"
            self.assertTrue(validator.validate_and_report(raw, report))
            self.assertTrue(report.exists())

    def test_adaptive_threshold_computes_threshold_trend_and_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "phase0_decisions.log"
            log_path.write_text(
                json.dumps(
                    [
                        {"overall_pass": True, "metrics": {"psnr": 20, "ssim": 0.7, "lpips": 0.15}},
                        {"overall_pass": True, "metrics": {"psnr": 22, "ssim": 0.75, "lpips": 0.12}},
                        {"action": "approved", "metrics": {"psnr": 24, "ssim": 0.8, "lpips": 0.1}},
                    ]
                ),
                encoding="utf-8",
            )

            threshold = AdaptiveThreshold(str(log_path), window=3)
            self.assertLess(threshold.get_threshold("psnr", base=25.0, min_threshold=10), 25.0)
            self.assertGreater(threshold.get_quality_score(25.0, 0.8, 0.1), 0.0)
            self.assertEqual(threshold.get_trend("psnr"), "improving")
            self.assertIn(threshold.recommend_action("psnr", 26.0, 20.0), {"approve", "investigate", "retrain"})


if __name__ == "__main__":
    unittest.main()














