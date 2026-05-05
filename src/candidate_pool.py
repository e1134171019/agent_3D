"""Candidate pool builder for Phase-0 decision contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import validate_candidate_pool, write_json
from src.outcome_feedback import OutcomeFeedbackHistory


class ProblemLayerAnalyzer:
    """Single source of truth for problem-layer inference and aggregation."""

    VALID_LAYERS = {"data", "parameter", "framework"}

    @classmethod
    def resolve(cls, entry: dict[str, Any], evaluation: dict[str, Any]) -> str:
        raw = entry.get("problem_layer") or evaluation.get("problem_layer")
        explicit = str(raw).strip().lower() if raw is not None else ""
        if explicit in cls.VALID_LAYERS:
            return explicit
        return cls.infer(entry, evaluation)

    @staticmethod
    def infer(entry: dict[str, Any], evaluation: dict[str, Any]) -> str:
        source = str(entry.get("stage", "")).lower()
        text_parts = [
            source,
            str(entry.get("proposal_text", "")).lower(),
            str(entry.get("action_reason", "")).lower(),
            str(evaluation.get("diagnosis", "")).lower(),
            str(evaluation.get("reason", "")).lower(),
            str(evaluation.get("decision_note", "")).lower(),
        ]
        text = " ".join(part for part in text_parts if part)

        data_keywords = ("pointcloud", "sfm", "colmap", "frame", "image", "camera", "feature", "match")
        parameter_keywords = (
            "param",
            "validation",
            "threshold",
            "opacity",
            "cap_max",
            "antialiased",
            "psnr",
            "ssim",
            "lpips",
            "train",
        )
        framework_keywords = ("unity", "import", "export", "recovery", "strategy", "mcmc", "glomap", "lightglue", "framework")

        if any(keyword in text for keyword in data_keywords):
            return "data"
        if any(keyword in text for keyword in parameter_keywords):
            return "parameter"
        if any(keyword in text for keyword in framework_keywords):
            return "framework"
        return "framework"

    @classmethod
    def aggregate(cls, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        from collections import Counter

        layers = [str(candidate.get("problem_layer", "framework")).strip().lower() for candidate in candidates]
        normalized_layers = [layer if layer in cls.VALID_LAYERS else "framework" for layer in layers]
        counts = Counter(normalized_layers)
        dominant_layer = counts.most_common(1)[0][0] if counts else "framework"
        return {
            "dominant_layer": dominant_layer,
            "layer_counts": dict(counts),
            "candidate_ids": {
                layer: [
                    candidate.get("candidate_id")
                    for candidate in candidates
                    if (str(candidate.get("problem_layer", "framework")).strip().lower() or "framework") == layer
                ]
                for layer in counts
            },
        }


class Phase0CandidatePoolBuilder:
    """Build a structured candidate pool from stage-level proposal logs."""

    def __init__(self, run_id: str, contract_stage: str):
        self.run_id = run_id
        self.contract_stage = contract_stage

    def build(
        self,
        decision_log: list[dict[str, Any]],
        output_path: Path,
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        history_summary = self._load_history_summary(output_path)
        for entry in decision_log:
            evaluation = entry.get("evaluation", {}) or {}
            source_module = entry.get("stage", "unknown")
            blocked_by = self._extract_blocked_by(entry, evaluation)
            confidence = self._extract_confidence(evaluation)
            history_signal = self._extract_history_signal(history_summary, source_module)
            problem_layer = ProblemLayerAnalyzer.resolve(entry, evaluation)
            rank_score = self._rank_candidate(confidence, history_signal, blocked_by)
            candidate = {
                "candidate_id": entry.get("proposal_id", "unknown"),
                "source_module": source_module,
                "scope": "map_building",
                "proposal_type": "stage_proposal",
                "title": entry.get("proposal_text", ""),
                "rationale": entry.get("action_reason", ""),
                "params": {},
                "expected_gain": self._extract_expected_gain(evaluation),
                "expected_risk": self._extract_expected_risk(evaluation, entry),
                "estimated_cost": "unknown",
                "blocked_by": blocked_by,
                "evidence": {
                    "evaluation": evaluation,
                    "event_emitted": entry.get("event_emitted"),
                    "action": entry.get("action"),
                },
                "confidence": confidence,
                "history_signal": history_signal,
                "problem_layer": problem_layer,
                "rank_score": rank_score,
            }
            candidates.append(candidate)

        candidates.sort(key=lambda item: (item.get("rank_score", 0.0), item.get("confidence", 0.0)), reverse=True)
        payload = {
            "schema_version": 1,
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "contract_stage": self.contract_stage,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        payload = validate_candidate_pool(payload, source_path=output_path)
        write_json(output_path, payload)
        return payload

    @staticmethod
    def _history_root(output_path: Path) -> Path:
        if len(output_path.parents) >= 3:
            return output_path.parents[2]
        return output_path.parent

    def _load_history_summary(self, output_path: Path) -> dict[str, dict[str, Any]]:
        history = OutcomeFeedbackHistory(self._history_root(output_path))
        return history.summarize_by_source_module(exclude_path=output_path.parent / "outcome_feedback.json")

    @staticmethod
    def _extract_history_signal(
        history_summary: dict[str, dict[str, Any]],
        source_module: str,
    ) -> dict[str, Any]:
        defaults = {
            "previous_runs": 0,
            "accepted_runs": 0,
            "held_runs": 0,
            "human_review_runs": 0,
            "human_override_runs": 0,
            "decision_useful_runs": 0,
            "decision_unuseful_runs": 0,
            "labeled_runs": 0,
            "wasted_runs": 0,
            "repeat_error_runs": 0,
            "accepted_rate": 0.0,
            "effectiveness_rate": 0.0,
            "human_override_rate": 0.0,
            "wasted_run_rate": 0.0,
            "repeat_error_rate": 0.0,
        }
        return dict(history_summary.get(source_module, defaults))

    @staticmethod
    def _rank_candidate(
        confidence: float,
        history_signal: dict[str, Any],
        blocked_by: list[str],
    ) -> float:
        score = confidence
        previous_runs = int(history_signal.get("previous_runs", 0) or 0)
        if previous_runs > 0:
            accepted_rate = float(history_signal.get("accepted_rate", 0.0) or 0.0)
            labeled_runs = int(history_signal.get("labeled_runs", 0) or 0)
            effectiveness_rate = float(history_signal.get("effectiveness_rate", 0.0) or 0.0)
            repeat_error_rate = float(history_signal.get("repeat_error_rate", 0.0) or 0.0)
            history_score = effectiveness_rate if labeled_runs else accepted_rate
            score = (confidence * 0.55) + (history_score * 0.45)
            score -= repeat_error_rate * 0.2
        if blocked_by:
            score -= 0.15
        return round(min(max(score, 0.0), 1.0), 4)

    @staticmethod
    def _extract_expected_gain(evaluation: dict[str, Any]) -> str:
        for key in ("decision_note", "reason", "diagnosis", "summary"):
            value = evaluation.get(key)
            if value:
                return str(value)
        return "stage evaluation completed"

    @staticmethod
    def _extract_expected_risk(evaluation: dict[str, Any], entry: dict[str, Any]) -> str:
        if entry.get("action") == "skipped":
            return "prerequisites missing"
        if evaluation.get("overall_pass") is False:
            return "validation not yet passing"
        return "unknown"

    @staticmethod
    def _extract_blocked_by(entry: dict[str, Any], evaluation: dict[str, Any]) -> list[str]:
        blocked_by: list[str] = []
        if entry.get("action") == "skipped":
            blocked_by.append(entry.get("action_reason", "stage_skipped"))
        if evaluation.get("overall_pass") is False:
            blocked_by.append("overall_pass_false")
        return blocked_by

    @staticmethod
    def _extract_confidence(evaluation: dict[str, Any]) -> float:
        raw = evaluation.get("confidence")
        try:
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            pass
        return 0.5



