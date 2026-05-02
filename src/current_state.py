"""Current state builder for Phase-0 decision orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import validate_current_state, write_json
from src.candidate_pool import ProblemLayerAnalyzer


class Phase0CurrentStateBuilder:
    """Build a minimal current_state object for the active decision cycle."""

    def __init__(
        self,
        run_id: str,
        contract_stage: str,
        contract_status: str,
        source_contract: str,
        run_root: str,
    ):
        self.run_id = run_id
        self.contract_stage = contract_stage
        self.contract_status = contract_status
        self.source_contract = source_contract
        self.run_root = run_root

    def build(
        self,
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        next_steps = report_data.get("next_steps", [])
        problem_layer_signal = self._problem_layer_signal(candidate_pool)
        payload = {
            "schema_version": 1,
            "state_id": f"{self.run_id}:{self._shared_stage_name()}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "phase": "phase0",
            "active_pack": "map_building",
            "current_best": report_data.get("recommendation", f"{self._shared_stage_name()}:{self.contract_status}"),
            "next_focus": next_steps[0] if next_steps else f"resolve_{self._shared_stage_name()}",
            "allowed_actions": self._allowed_actions(),
            "blocked_actions": self._blocked_actions(),
            "blacklist": [],
            "source_docs": [
                r"C:\3d-recon-pipeline\AI代理作業守則.md",
                r"C:\3d-recon-pipeline\專案願景與當前狀態.md",
                self.source_contract,
            ],
            "updated_at": datetime.now().isoformat(),
            "context": {
                "run_id": self.run_id,
                "run_root": self.run_root,
                "contract_stage": self.contract_stage,
                "contract_status": self.contract_status,
                "candidate_count": len(candidate_pool.get("candidates", [])),
                "problem_layer_signal": problem_layer_signal,
            },
        }
        payload = validate_current_state(payload, source_path=output_path)
        write_json(output_path, payload)
        return payload

    def _shared_stage_name(self) -> str:
        mapping = {
            "sfm_complete": "sfm",
            "train_complete": "train",
            "export_complete": "export",
        }
        return mapping.get(self.contract_stage, self.contract_stage)

    def _allowed_actions(self) -> list[str]:
        stage_name = self._shared_stage_name()
        if stage_name == "sfm":
            return ["proceed_to_train", "recover_sfm", "human_review"]
        if stage_name == "train":
            return ["proceed_to_export", "review_training", "human_review"]
        if stage_name == "export":
            return ["export_verified", "review_export", "close_phase", "human_review"]
        return ["review", "human_review"]

    def _blocked_actions(self) -> list[str]:
        stage_name = self._shared_stage_name()
        if stage_name == "sfm":
            return ["proceed_to_export", "close_phase"]
        if stage_name == "train":
            return ["proceed_to_train", "close_phase"]
        if stage_name == "export":
            return ["proceed_to_train"]
        return []

    @staticmethod
    def _problem_layer_signal(candidate_pool: dict[str, Any]) -> dict[str, Any]:
        candidates = candidate_pool.get("candidates", [])
        signal_candidates = candidates
        aggregate = ProblemLayerAnalyzer.aggregate(signal_candidates)
        return {
            "dominant_layer": aggregate["dominant_layer"],
            "layer_counts": aggregate["layer_counts"],
            "candidate_ids": aggregate["candidate_ids"],
            "source": "all_candidates",
            "ignored_skipped_count": sum(
                1 for candidate in candidates if (candidate.get("evidence", {}) or {}).get("action") == "skipped"
            ),
            "ignored_support_count": 0,
        }



