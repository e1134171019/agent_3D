"""Single arbiter for Phase-0 map-building decisions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import validate_arbiter_decision, write_json


class Phase0Arbiter:
    """Reduce a candidate pool and phase report to one formal decision."""

    def __init__(self, run_id: str, contract_stage: str, contract_path: str, run_root: str):
        self.run_id = run_id
        self.contract_stage = contract_stage
        self.contract_path = contract_path
        self.run_root = run_root

    def decide(
        self,
        current_state: dict[str, Any],
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
        state_ref: str,
        output_path: Path,
        history_signal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage_name = self._shared_stage_name()
        state = report_data or {}
        dominant_layer = self._dominant_problem_layer(current_state)

        pointcloud_pass = bool(state.get("pointcloud_pass", False))
        validation_ready = bool(state.get("validation_ready", False))
        validation_pass = bool(state.get("validation_pass", False))
        import_success = bool(state.get("import_success", False))

        can_proceed, decision, next_action = self._stage_outcome(
            stage_name=stage_name,
            pointcloud_pass=pointcloud_pass,
            validation_pass=validation_pass,
            import_success=import_success,
            dominant_layer=dominant_layer,
        )
        selected_candidate_id = self._select_candidate(
            stage_name=stage_name,
            can_proceed=can_proceed,
            validation_ready=validation_ready,
            dominant_layer=dominant_layer,
            candidate_pool=candidate_pool,
        )

        selected_candidate_id = selected_candidate_id or self._first_candidate_id(candidate_pool)
        all_ids = [item.get("candidate_id") for item in candidate_pool.get("candidates", [])]
        rejected_candidate_ids = [item for item in all_ids if item and item != selected_candidate_id]

        written_at = datetime.now().isoformat()
        payload = {
            "schema_version": 1,
            "decision_id": f"{self.run_id}:{stage_name}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": written_at,
            "written_at": written_at,
            "state_ref": state_ref,
            "event_ref": self.contract_path,
            "run_id": self.run_id,
            "run_root": self.run_root,
            "decision_stage": stage_name,
            "active_pack": current_state.get("active_pack", "unknown"),
            "selected_candidate_id": selected_candidate_id,
            "rejected_candidate_ids": rejected_candidate_ids,
            "decision": decision,
            "reason": self._build_reason(state.get("recommendation", "N/A"), can_proceed, dominant_layer),
            "next_action": next_action,
            "can_proceed": can_proceed,
            "requires_human_review": not can_proceed,
            "decision_context": self._decision_context(
                current_state=current_state,
                history_signal=history_signal,
                dominant_layer=dominant_layer,
                stage_name=stage_name,
                candidate_pool=candidate_pool,
            ),
        }
        payload = validate_arbiter_decision(payload, source_path=output_path)
        write_json(output_path, payload)
        return payload

    def _shared_stage_name(self) -> str:
        mapping = {
            "sfm_complete": "sfm",
            "train_complete": "train",
            "export_complete": "export",
        }
        return mapping.get(self.contract_stage, self.contract_stage)

    @classmethod
    def _stage_outcome(
        cls,
        *,
        stage_name: str,
        pointcloud_pass: bool,
        validation_pass: bool,
        import_success: bool,
        dominant_layer: str,
    ) -> tuple[bool, str, dict[str, str]]:
        if stage_name == "sfm":
            can_proceed = pointcloud_pass
            decision = "proceed_to_train" if can_proceed else "hold_train"
            proceed_action = "train"
        elif stage_name == "train":
            can_proceed = validation_pass
            decision = "proceed_to_export" if can_proceed else "hold_export"
            proceed_action = "export"
        elif stage_name == "export":
            can_proceed = import_success
            decision = "export_verified" if can_proceed else "hold_phase_close"
            proceed_action = "close_phase"
        else:
            can_proceed = validation_pass
            decision = "proceed" if can_proceed else "hold"
            proceed_action = "review"

        next_action_type = proceed_action if can_proceed else cls._hold_action_type(stage_name, dominant_layer)
        return can_proceed, decision, {"type": next_action_type}

    @classmethod
    def _select_candidate(
        cls,
        *,
        stage_name: str,
        can_proceed: bool,
        validation_ready: bool,
        dominant_layer: str,
        candidate_pool: dict[str, Any],
    ) -> str | None:
        if stage_name == "sfm":
            if can_proceed:
                return cls._candidate_by_id(candidate_pool, "PCV-001") or cls._best_ranked_candidate(
                    candidate_pool,
                    preferred_layer="data",
                    fallback="PCV-001",
                )
            return cls._best_ranked_candidate(candidate_pool, preferred_layer=dominant_layer, fallback="PCV-001")

        if stage_name == "train":
            if can_proceed:
                if validation_ready:
                    return cls._candidate_by_id(candidate_pool, "VAL-001") or cls._best_ranked_candidate(
                        candidate_pool,
                        preferred_layer="parameter",
                        fallback="VAL-001",
                    )
                return cls._best_ranked_candidate(candidate_pool)
            fallback = "REC-001"
            if dominant_layer == "parameter" and validation_ready:
                fallback = "VAL-001"
            elif dominant_layer == "data":
                fallback = "PCV-001"
            return cls._best_ranked_candidate(
                candidate_pool,
                preferred_layer=dominant_layer,
                fallback=fallback,
            )

        if stage_name == "export":
            if can_proceed:
                return cls._best_ranked_candidate(candidate_pool)
            fallback = "REC-001"
            if dominant_layer == "parameter":
                fallback = "PPG-001"
            elif dominant_layer == "data":
                fallback = "PCV-001"
            return cls._best_ranked_candidate(
                candidate_pool,
                preferred_layer=dominant_layer,
                fallback=fallback,
            )

        if can_proceed:
            return cls._best_ranked_candidate(candidate_pool)
        return cls._best_ranked_candidate(candidate_pool, preferred_layer=dominant_layer)

    @staticmethod
    def _candidate_sort_key(item: dict[str, Any]) -> tuple[float, float]:
        rank_score = item.get("rank_score", 0.0)
        confidence = item.get("confidence", 0.0)
        try:
            rank_value = float(rank_score)
        except (TypeError, ValueError):
            rank_value = 0.0
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        return rank_value, confidence_value

    @classmethod
    def _best_ranked_candidate(
        cls,
        candidate_pool: dict[str, Any],
        *,
        preferred_layer: str | None = None,
        fallback: str | None = None,
    ) -> str | None:
        ranked_candidates = sorted(
            candidate_pool.get("candidates", []),
            key=cls._candidate_sort_key,
            reverse=True,
        )
        for item in ranked_candidates:
            candidate_id = item.get("candidate_id")
            if not candidate_id:
                continue
            if preferred_layer is None:
                return candidate_id
            if str(item.get("problem_layer", "")).strip() == preferred_layer:
                return candidate_id
        return fallback

    @staticmethod
    def _first_candidate_id(candidate_pool: dict[str, Any]) -> str | None:
        for item in candidate_pool.get("candidates", []):
            candidate_id = item.get("candidate_id")
            if candidate_id:
                return candidate_id
        return None

    @staticmethod
    def _candidate_by_id(candidate_pool: dict[str, Any], candidate_id: str) -> str | None:
        for item in candidate_pool.get("candidates", []):
            if item.get("candidate_id") == candidate_id:
                return candidate_id
        return None

    @staticmethod
    def _dominant_problem_layer(current_state: dict[str, Any]) -> str:
        context = current_state.get("context", {}) if isinstance(current_state.get("context"), dict) else {}
        signal = context.get("problem_layer_signal", {}) if isinstance(context.get("problem_layer_signal"), dict) else {}
        layer = str(signal.get("dominant_layer", "framework")).strip()
        return layer or "framework"

    @staticmethod
    def _candidate_for_layer(candidate_pool: dict[str, Any], layer: str, fallback: str | None = None) -> str | None:
        for item in candidate_pool.get("candidates", []):
            if str(item.get("problem_layer", "")).strip() == layer and item.get("candidate_id"):
                return item.get("candidate_id")
        return fallback

    @staticmethod
    def _hold_action_type(stage_name: str, dominant_layer: str) -> str:
        if dominant_layer == "data":
            return "recover_upstream" if stage_name != "sfm" else "recover_sfm"
        if dominant_layer == "parameter":
            if stage_name == "sfm":
                return "review_sfm_params"
            if stage_name == "train":
                return "review_training"
            if stage_name == "export":
                return "review_export"
            return "review_parameters"
        return "switch_strategy"

    @staticmethod
    def _build_reason(recommendation: Any, can_proceed: bool, dominant_layer: str) -> str:
        base = str(recommendation or "N/A")
        if can_proceed:
            return base
        return f"{base} | dominant_problem_layer={dominant_layer}"

    @staticmethod
    def _decision_context(
        *,
        current_state: dict[str, Any],
        history_signal: dict[str, Any] | None,
        dominant_layer: str,
        stage_name: str,
        candidate_pool: dict[str, Any],
    ) -> dict[str, Any]:
        history = history_signal or {}
        recent_window = history.get("recent_window", {}) if isinstance(history.get("recent_window"), dict) else {}
        ai_exit_trend = history.get("ai_exit_readiness_trend", {}) if isinstance(history.get("ai_exit_readiness_trend"), dict) else {}
        ai_exit = history.get("ai_exit_readiness", {}) if isinstance(history.get("ai_exit_readiness"), dict) else {}
        return {
            "stage_name": stage_name,
            "dominant_problem_layer": dominant_layer,
            "active_pack": current_state.get("active_pack", "unknown"),
            "candidate_count": len(candidate_pool.get("candidates", [])),
            "history_signal": {
                "total_decisions": history.get("total_decisions", 0),
                "window_size": history.get("window_size", 0),
                "overall": history.get("overall", {}),
                "recent_window": recent_window,
                "ai_exit_readiness": ai_exit,
                "ai_exit_readiness_trend": ai_exit_trend,
            },
        }
