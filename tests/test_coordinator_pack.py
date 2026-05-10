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

from src.coordinator import ArtifactResolver, Phase0Coordinator, Phase0ReportGenerator
from src.map_building_pack import MapBuildingPackRunner


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, event_name: str, data: dict | None = None) -> None:
        self.events.append({"event": event_name, "data": data or {}})


class FakeCoordinator:
    def __init__(self, root: Path, stage: str):
        self.root = root
        self.contract_stage = stage
        self.contract_status = "completed"
        self.output_path = root / "decision"
        self.output_path.mkdir(parents=True)
        self.event_bus = FakeEventBus()
        self.decisions = []

        self.pointcloud_report_path = write_json(
            root / "pointcloud_report.json",
            {
                "can_proceed_to_3dgs": True,
                "cameras_count": 8,
                "images_count": 120,
                "points3d_count": 70000,
                "diagnosis": "pointcloud ok",
            },
        )
        self.training_stats_path = write_json(
            root / "val_step29999.json",
            {"psnr": 25.0, "ssim": 0.91, "lpips": 0.05, "iteration": 30000},
        )

    def _append_decision(self, **kwargs) -> None:
        self.decisions.append(kwargs)


class CoordinatorIntegrationTests(unittest.TestCase):
    def test_artifact_resolver_uses_alias_then_stable_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolver = ArtifactResolver(
                artifacts={
                    "stats_json": str(root / "custom_stats.json"),
                    "ply": str(root / "custom.ply"),
                },
                run_root=root / "run",
            )

            self.assertEqual(resolver.resolve("training_stats"), root / "custom_stats.json")
            self.assertEqual(resolver.resolve("ply_file"), root / "custom.ply")
            self.assertEqual(
                resolver.resolve("pointcloud_report"),
                root / "run" / "reports" / "pointcloud_validation_report.json",
            )

    def test_phase0_report_generator_maps_stage_recommendations(self):
        train_report = Phase0ReportGenerator.generate(
            run_id="run1",
            contract_stage="train_complete",
            contract_status="completed",
            shared_stage_name="train",
            artifacts={},
            metrics={},
            params={},
            pack_result={"pointcloud_ready": True},
            validation_report={"overall_pass": False},
            validation_ready=True,
            decision_log_count=3,
        )
        sfm_report = Phase0ReportGenerator.generate(
            run_id="run2",
            contract_stage="sfm_complete",
            contract_status="completed",
            shared_stage_name="sfm",
            artifacts={},
            metrics={},
            params={},
            pack_result={"pointcloud_ready": True},
            validation_report={},
            validation_ready=False,
            decision_log_count=2,
        )

        self.assertEqual(train_report["recommendation"], "hold_export")
        self.assertEqual(train_report["next_steps"], ["review_training_quality"])
        self.assertTrue(train_report["validation_ready"])
        self.assertFalse(train_report["validation_pass"])
        self.assertEqual(sfm_report["recommendation"], "proceed_to_train")
        self.assertEqual(sfm_report["next_steps"], ["start_3dgs_training"])

        with tempfile.TemporaryDirectory() as tmp:
            ply = Path(tmp) / "point_cloud_unity.ply"
            ply.write_bytes(b"ply\n")
            export_report = Phase0ReportGenerator.generate(
                run_id="run3",
                contract_stage="export_complete",
                contract_status="completed",
                shared_stage_name="export",
                artifacts={"ply_file": str(ply)},
                metrics={},
                params={"unity": True},
                pack_result={},
                validation_report={},
                validation_ready=False,
                decision_log_count=1,
            )
        self.assertTrue(export_report["import_success"])
        self.assertEqual(export_report["import_success_source"], "completed_unity_ply_artifact")
        self.assertEqual(export_report["recommendation"], "export_verified")

    def test_coordinator_writes_core_audit_and_shared_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "prod"
            events = production / "outputs" / "agent_events"
            decisions = production / "outputs" / "agent_decisions"
            output = root / "agent_outputs"
            run_root = root / "run"
            contract_path = events / "latest_train_complete.json"
            events.mkdir(parents=True)
            write_json(
                contract_path,
                {
                    "schema_version": 1,
                    "timestamp": "2026-04-26T00:00:00",
                    "run_id": "run with spaces/colon",
                    "stage": "train_complete",
                    "status": "completed",
                    "run_root": str(run_root),
                    "artifacts": {"stats_json": str(run_root / "stats.json")},
                    "metrics": {"lpips": 0.21},
                    "params": {"train_mode": "mcmc"},
                },
            )

            def fake_run(pack_runner):
                coord = pack_runner.coordinator
                coord.event_bus.emit("validation_failed", {"stats": str(coord.training_stats_path)})
                coord._append_decision(
                    stage="MapValidator",
                    proposal_id="VAL-001",
                    proposal_text="validation failed",
                    evaluation={"overall_pass": False, "confidence": 0.8},
                    action="approved_with_fail",
                    action_reason="quality failed",
                    event_emitted="validation_failed",
                )
                write_json(
                    coord.output_path / "phase0_report.json",
                    {
                        "recommendation": "hold export",
                        "next_steps": ["review training"],
                        "pointcloud_pass": True,
                        "validation_ready": True,
                        "validation_pass": False,
                        "import_success": False,
                    },
                )
                return {"validation_ready": True}

            with mock.patch("src.map_building_pack.MapBuildingPackRunner.run", fake_run):
                result = Phase0Coordinator(
                    production_path=str(production),
                    events_root=str(events),
                    output_root=str(output),
                    contract_path=str(contract_path),
                    unity_project_path=str(root / "unity"),
                    decisions_root=str(decisions),
                ).run()

            out_dir = Path(result["output_root"])
            self.assertTrue((out_dir / "contract_context.json").exists())
            self.assertTrue((out_dir / "candidate_pool.json").exists())
            self.assertTrue((out_dir / "current_state.json").exists())
            self.assertTrue((out_dir / "arbiter_decision.json").exists())
            self.assertTrue((out_dir / "outcome_feedback.json").exists())
            self.assertTrue((out_dir / "observability.json").exists())
            self.assertTrue((decisions / "latest_train_decision.json").exists())
            self.assertIn("run_with_spaces_colon", str(out_dir))
            shared = json.loads((decisions / "latest_train_decision.json").read_text(encoding="utf-8"))
            self.assertEqual(shared["decision_stage"], "train")
            self.assertFalse(shared["can_proceed"])
            observability = json.loads((out_dir / "observability.json").read_text(encoding="utf-8"))
            self.assertEqual(observability["event_trace"]["event_count"], 1)
            self.assertEqual(observability["candidate_recall"], 1.0)
            self.assertIsNotNone(observability["decision_latency_ms"])
            self.assertIn("ai_exit_readiness_trend", observability)
            self.assertIn("alerts", observability)

    def test_coordinator_builds_phase0_report_when_pack_does_not_write_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "prod"
            events = production / "outputs" / "agent_events"
            decisions = production / "outputs" / "agent_decisions"
            output = root / "agent_outputs"
            run_root = root / "run"
            contract_path = events / "latest_train_complete.json"
            events.mkdir(parents=True)
            write_json(
                contract_path,
                {
                    "schema_version": 1,
                    "timestamp": "2026-04-26T00:00:00",
                    "run_id": "run1",
                    "stage": "train_complete",
                    "status": "completed",
                    "run_root": str(run_root),
                    "artifacts": {},
                    "metrics": {"lpips": 0.21},
                    "params": {},
                },
            )

            def fake_run(pack_runner):
                coord = pack_runner.coordinator
                coord._append_decision(
                    stage="PointCloudValidator",
                    proposal_id="PCV-001",
                    proposal_text="pointcloud ok",
                    evaluation={"can_proceed_to_3dgs": True, "confidence": 0.9},
                    action="approved",
                    action_reason="upstream_report_read",
                    problem_layer="data",
                )
                coord._append_decision(
                    stage="MapValidator",
                    proposal_id="VAL-001",
                    proposal_text="validation missing",
                    evaluation={"overall_pass": False, "confidence": 0.7},
                    action="skipped",
                    action_reason="training_stats_missing",
                    problem_layer="parameter",
                )
                return {"pointcloud_ready": True, "validation_ready": False}

            with mock.patch("src.map_building_pack.MapBuildingPackRunner.run", fake_run):
                result = Phase0Coordinator(
                    production_path=str(production),
                    events_root=str(events),
                    output_root=str(output),
                    contract_path=str(contract_path),
                    decisions_root=str(decisions),
                ).run()

            report = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
            self.assertTrue(report["pointcloud_pass"])
            self.assertFalse(report["validation_ready"])
            self.assertFalse(report["validation_pass"])
            self.assertEqual(report["recommendation"], "hold_export")
            self.assertEqual(report["next_steps"], ["review_training_quality"])

    def test_coordinator_replaces_stale_pack_report_for_different_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "prod"
            events = production / "outputs" / "agent_events"
            decisions = production / "outputs" / "agent_decisions"
            output = root / "agent_outputs"
            run_root = root / "run"
            contract_path = events / "latest_train_complete.json"
            events.mkdir(parents=True)
            write_json(
                contract_path,
                {
                    "schema_version": 1,
                    "timestamp": "2026-04-26T00:00:00",
                    "run_id": "fresh-run",
                    "stage": "train_complete",
                    "status": "completed",
                    "run_root": str(run_root),
                    "artifacts": {},
                    "metrics": {},
                    "params": {},
                },
            )

            def fake_run(pack_runner):
                coord = pack_runner.coordinator
                write_json(
                    coord.output_path / "phase0_report.json",
                    {
                        "run_id": "old-run",
                        "contract_stage": "export_complete",
                        "recommendation": "stale",
                    },
                )
                return {"pointcloud_ready": True, "validation_ready": False}

            with mock.patch("src.map_building_pack.MapBuildingPackRunner.run", fake_run):
                result = Phase0Coordinator(
                    production_path=str(production),
                    events_root=str(events),
                    output_root=str(output),
                    contract_path=str(contract_path),
                    decisions_root=str(decisions),
                ).run()

            out_dir = Path(result["output_root"])
            report = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
            self.assertEqual(report["run_id"], "fresh-run")
            self.assertEqual(report["contract_stage"], "train_complete")
            self.assertTrue(list(out_dir.glob("phase0_report__stale_*.json")))


class MapBuildingPackIntegrationTests(unittest.TestCase):
    def test_full_train_contract_path_runs_all_strategy_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeCoordinator(root, "train_complete")
            result = MapBuildingPackRunner(fake).run()

            self.assertTrue(result["pointcloud_ready"])
            self.assertTrue(result["validation_ready"])
            stages = {entry["stage"] for entry in fake.decisions}
            self.assertIn("ProductionParamGate", stages)
            self.assertTrue(all(entry.get("problem_layer") in {"data", "parameter", "framework"} for entry in fake.decisions))

    def test_sfm_contract_path_skips_downstream_validation_and_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeCoordinator(root, "sfm_complete")
            write_json(
                fake.pointcloud_report_path,
                {
                    "can_proceed_to_3dgs": False,
                    "cameras_count": 1,
                    "points3d_count": 10,
                    "diagnosis": "too sparse",
                },
            )

            result = MapBuildingPackRunner(fake).run()

            self.assertFalse(result["pointcloud_ready"])
            self.assertFalse(result["validation_ready"])
            reasons = {entry["action_reason"] for entry in fake.decisions}
            self.assertIn("sfm_stage_only", reasons)
            self.assertTrue(all(entry.get("problem_layer") in {"data", "parameter", "framework"} for entry in fake.decisions))


if __name__ == "__main__":
    unittest.main()






