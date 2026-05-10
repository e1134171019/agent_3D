"""Shared decision payload mapper for production-facing outbox files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import validate_shared_decision


class Phase0SharedDecisionMapper:
    """Map arbiter output and report state into the shared decision schema."""

    def __init__(
        self,
        run_id: str,
        source_contract: str,
        source_stage: str,
        source_status: str,
        run_root: str,
        metrics: dict[str, Any],
    ):
        self.run_id = run_id
        self.source_contract = source_contract
        self.source_stage = source_stage
        self.source_status = source_status
        self.run_root = run_root
        self.metrics = metrics

    def build(
        self,
        report_data: dict[str, Any],
        arbiter_decision: dict[str, Any],
        reports: dict[str, str],
        source_path: str | Path = "",
    ) -> dict[str, Any]:
        pointcloud_pass = bool(report_data.get("pointcloud_pass", False))
        validation_ready = bool(report_data.get("validation_ready", False))
        validation_pass = bool(report_data.get("validation_pass", False))
        import_success = bool(report_data.get("import_success", False))

        payload = {
            "schema_version": 1,
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "source_contract": self.source_contract,
            "source_stage": self.source_stage,
            "source_status": self.source_status,
            "run_root": self.run_root,
            "decision_stage": arbiter_decision.get("decision_stage", "unknown"),
            "decision_gate": self._decision_gate(arbiter_decision.get("decision_stage", "unknown")),
            "decision": arbiter_decision.get("decision", "hold"),
            "can_proceed": bool(arbiter_decision.get("can_proceed", False)),
            "recommendation": report_data.get("recommendation", "N/A"),
            "next_steps": report_data.get("next_steps", []),
            "metrics": self.metrics,
            "arbiter": {
                "decision_id": arbiter_decision.get("decision_id"),
                "selected_candidate_id": arbiter_decision.get("selected_candidate_id"),
                "rejected_candidate_ids": arbiter_decision.get("rejected_candidate_ids", []),
                "reason": arbiter_decision.get("reason", "N/A"),
                "requires_human_review": bool(arbiter_decision.get("requires_human_review", False)),
                "next_action": arbiter_decision.get("next_action", {}),
            },
            "profiles": {
                "sfm": report_data.get("sfm_profile", "N/A"),
                "train": report_data.get("train_profile", "N/A"),
                "unity_export": report_data.get("unity_export_profile", "N/A"),
            },
            "state": {
                "pointcloud_pass": pointcloud_pass,
                "validation_ready": validation_ready,
                "validation_pass": validation_pass,
                "import_success": import_success,
                "recovery_state": report_data.get("recovery_state", "N/A"),
                "recovery_category": report_data.get("recovery_category", "N/A"),
                "recovery_severity": report_data.get("recovery_severity", "N/A"),
                "recovery_responsible_layer": report_data.get("recovery_responsible_layer", "N/A"),
            },
            "reports": reports,
        }
        return validate_shared_decision(payload, source_path=source_path)

    @staticmethod
    def _decision_gate(stage_name: str) -> str:
        mapping = {
            "sfm": "gate_1",
            "train": "gate_2_3",
            "export": "unity_gate",
        }
        return mapping.get(stage_name, "unknown")
