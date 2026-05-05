"""Map-building strategy pack runner for the decision layer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.coordinator import Phase0Coordinator


class MapBuildingPackRunner:
    """Execute map-building specific phase0 stages for a coordinator."""

    def __init__(self, coordinator: "Phase0Coordinator"):
        self.coordinator = coordinator

    def run(self) -> dict[str, Any]:
        pointcloud_ready = self._run_stage_0()
        validation_ready = self._run_stage_1(pointcloud_ready)
        self._run_stage_2()
        return {
            "pointcloud_ready": pointcloud_ready,
            "validation_ready": validation_ready,
        }

    def _run_stage_0(self) -> bool:
        from agents.phase0.pointcloud_validator import PointCloudValidator

        agent = PointCloudValidator(verbose=True)
        output_json = self.coordinator.output_path / "pointcloud_validation_report.json"
        report = agent.validate(self.coordinator.pointcloud_report_path)
        output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        can_proceed = bool(report.get("can_proceed_to_3dgs", False))
        event_name = "pointcloud_validated_ok" if can_proceed else "pointcloud_validation_failed"
        self.coordinator.event_bus.emit(event_name, {"contract_stage": self.coordinator.contract_stage})
        self.coordinator._append_decision(
            stage="PointCloudValidator",
            proposal_id="PCV-001",
            proposal_text=f"檢查 pointcloud report：{self.coordinator.pointcloud_report_path}",
            evaluation={
                "input_exists": self.coordinator.pointcloud_report_path.exists(),
                "can_proceed_to_3dgs": can_proceed,
                "diagnosis": report.get("diagnosis"),
            },
            action="approved" if can_proceed else "approved_with_fail",
            action_reason="upstream_report_read",
            event_emitted=event_name,
            problem_layer="data",
        )
        return can_proceed

    def _run_stage_1(self, pointcloud_ready: bool) -> bool:
        from agents.phase0.map_validator import MapValidator

        if self.coordinator.contract_stage == "sfm_complete":
            self.coordinator._append_decision(
                stage="MapValidator",
                proposal_id="VAL-001",
                proposal_text="sfm_complete 事件只做 Gate 1，跳過 3DGS 品質驗證",
                evaluation={"overall_pass": False, "reason": "sfm_stage_only"},
                action="skipped",
                action_reason="sfm_stage_only",
                problem_layer="data",
            )
            return False

        if not pointcloud_ready:
            self.coordinator._append_decision(
                stage="MapValidator",
                proposal_id="VAL-001",
                proposal_text="Stage 0 未通過，跳過 3DGS 品質驗證",
                evaluation={"overall_pass": False, "reason": "pointcloud_gate_failed"},
                action="skipped",
                action_reason="pointcloud_gate_failed",
                problem_layer="data",
            )
            return False

        if not self.coordinator.training_stats_path.exists():
            self.coordinator.event_bus.emit(
                "training_not_ready",
                {"expected_stats": str(self.coordinator.training_stats_path)},
            )
            self.coordinator._append_decision(
                stage="MapValidator",
                proposal_id="VAL-001",
                proposal_text=f"3DGS stats 尚未就緒：{self.coordinator.training_stats_path}",
                evaluation={"overall_pass": False, "reason": "training_stats_missing"},
                action="skipped",
                action_reason="training_stats_missing",
                event_emitted="training_not_ready",
                problem_layer="parameter",
            )
            return False

        agent = MapValidator(log_path=str(self.coordinator.output_path / "phase0_decisions.log"))
        proposal = agent.propose(str(self.coordinator.training_stats_path))
        evaluation = agent.evaluate()
        result = agent.execute(str(self.coordinator.output_path / "validation_report.json"))
        overall_pass = bool(evaluation.get("overall_pass", False))
        event_name = "validation_passed" if overall_pass else "validation_failed"
        self.coordinator.event_bus.emit(event_name, {"stats": str(self.coordinator.training_stats_path)})
        self.coordinator._append_decision(
            stage="MapValidator",
            proposal_id=proposal.get("proposal_id", "VAL-001"),
            proposal_text=proposal.get("proposal_text", "檢查 3DGS 品質"),
            evaluation=evaluation,
            action="approved" if result.get("status") == "success" else "approved_with_fail",
            action_reason=evaluation.get("decision_note", "validation_complete"),
            event_emitted=event_name,
            problem_layer="parameter",
        )
        return overall_pass

    def _run_stage_2(self) -> None:
        from agents.phase0.production_param_gate import ProductionParamGate

        agent = ProductionParamGate()
        pointcloud_report = self.coordinator.output_path / "pointcloud_validation_report.json"
        validation_report = self.coordinator.output_path / "validation_report.json"
        proposal = agent.propose(str(pointcloud_report), str(validation_report))
        evaluation = agent.evaluate()
        result = agent.execute(str(self.coordinator.output_path))
        if result.get("status") != "success":
            event_name = "production_params_failed"
            action = "approved_with_fail"
        elif evaluation.get("approved", False):
            event_name = "production_params_ready"
            action = "approved"
        else:
            event_name = "production_params_hold"
            action = "approved_with_fail"
        self.coordinator.event_bus.emit(event_name)
        self.coordinator._append_decision(
            stage="ProductionParamGate",
            proposal_id=proposal.get("proposal_id", "PPG-001"),
            proposal_text=proposal.get("proposal_text", "生成 SfM / 3DGS 參數建議"),
            evaluation=evaluation,
            action=action,
            action_reason=evaluation.get("reason", "production_params_generated"),
            event_emitted=event_name,
            problem_layer="parameter",
        )
