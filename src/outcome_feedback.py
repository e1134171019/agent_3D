"""Outcome feedback and learning-curve utilities for decision cycles."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.contract_io import read_json, validate_outcome_feedback, write_json


class OutcomeFeedbackHistory:
    """Read outcome feedback artifacts and expose ranking / learning summaries."""

    def __init__(self, audit_root: str | Path):
        self.audit_root = Path(audit_root)

    def load_records(self, *, exclude_path: str | Path | None = None) -> list[dict[str, Any]]:
        if not self.audit_root.exists():
            return []

        exclude = Path(exclude_path).resolve() if exclude_path else None
        records: list[dict[str, Any]] = []
        for path in sorted(self.audit_root.glob("*/*/outcome_feedback.json")):
            try:
                if exclude is not None and path.resolve() == exclude:
                    continue
                payload = read_json(path, expect_object=True)
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def summarize_by_source_module(self, *, exclude_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
        return self._summarize_group(
            self.load_records(exclude_path=exclude_path),
            key="selected_source_module",
        )

    def summarize_by_problem_layer(self, *, exclude_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
        return self._summarize_group(
            self.load_records(exclude_path=exclude_path),
            key="problem_layer",
        )

    def build_learning_curve(
        self,
        *,
        exclude_path: str | Path | None = None,
        window: int = 20,
    ) -> dict[str, Any]:
        records = sorted(
            self.load_records(exclude_path=exclude_path),
            key=lambda item: str(item.get("recorded_at", "")),
        )
        total = len(records)
        recent = records[-window:] if window > 0 else records
        return {
            "schema_version": 1,
            "generated_at": datetime.now().isoformat(),
            "audit_root": str(self.audit_root),
            "total_decisions": total,
            "window_size": window,
            "overall": self._learning_metrics(records),
            "recent_window": self._learning_metrics(recent),
            "by_source_module": self._summarize_group(records, key="selected_source_module"),
            "by_problem_layer": self._summarize_group(records, key="problem_layer"),
            "timeline": self._timeline(records),
            "ai_exit_readiness": self._ai_exit_readiness(records, recent),
            "ai_exit_readiness_trend": self._ai_exit_readiness_trend(records, recent),
        }

    def write_learning_curve(self, output_path: str | Path, *, window: int = 20) -> dict[str, Any]:
        payload = self.build_learning_curve(window=window)
        write_json(output_path, payload)
        return payload

    @classmethod
    def _summarize_group(cls, records: list[dict[str, Any]], *, key: str) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = defaultdict(cls._empty_bucket)
        for record in records:
            group_name = str(record.get(key, "") or "unknown").strip()
            if not group_name:
                group_name = "unknown"
            cls._add_record(summary[group_name], record)
        return {name: cls._finalize_bucket(bucket) for name, bucket in summary.items()}

    @staticmethod
    def _empty_bucket() -> dict[str, Any]:
        return {
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

    @classmethod
    def _add_record(cls, bucket: dict[str, Any], record: dict[str, Any]) -> None:
        bucket["previous_runs"] += 1
        if record.get("outcome_status") == "accepted":
            bucket["accepted_runs"] += 1
        else:
            bucket["held_runs"] += 1
        if bool(record.get("requires_human_review", False)):
            bucket["human_review_runs"] += 1
        if bool(record.get("human_override", False)):
            bucket["human_override_runs"] += 1
        useful = cls._bool_or_none(record.get("decision_useful"))
        if useful is not None:
            bucket["labeled_runs"] += 1
            if useful:
                bucket["decision_useful_runs"] += 1
            else:
                bucket["decision_unuseful_runs"] += 1
        if bool(record.get("wasted_run", False)):
            bucket["wasted_runs"] += 1
        if bool(record.get("repeated_problem", False)):
            bucket["repeat_error_runs"] += 1

    @staticmethod
    def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
        total = int(bucket["previous_runs"])
        labeled = int(bucket["labeled_runs"])
        bucket["accepted_rate"] = round(bucket["accepted_runs"] / total, 4) if total else 0.0
        bucket["effectiveness_rate"] = round(bucket["decision_useful_runs"] / labeled, 4) if labeled else 0.0
        bucket["human_override_rate"] = round(bucket["human_override_runs"] / total, 4) if total else 0.0
        bucket["wasted_run_rate"] = round(bucket["wasted_runs"] / total, 4) if total else 0.0
        bucket["repeat_error_rate"] = round(bucket["repeat_error_runs"] / total, 4) if total else 0.0
        return dict(bucket)

    @classmethod
    def _learning_metrics(cls, records: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(records)
        labeled = [record for record in records if cls._bool_or_none(record.get("decision_useful")) is not None]
        useful = [record for record in labeled if cls._bool_or_none(record.get("decision_useful")) is True]
        token_values = [cls._float_or_none(record.get("token_cost_estimate")) for record in records]
        token_values = [value for value in token_values if value is not None]
        return {
            "decision_count": total,
            "labeled_decision_count": len(labeled),
            "recommendation_success_rate": round(len(useful) / len(labeled), 4) if labeled else 0.0,
            "human_override_rate": cls._rate(records, "human_override"),
            "repeat_error_rate": cls._rate(records, "repeated_problem"),
            "wasted_run_rate": cls._rate(records, "wasted_run"),
            "critical_bad_release_count": sum(1 for record in records if bool(record.get("critical_bad_release", False))),
            "token_per_decision": round(sum(token_values) / len(token_values), 2) if token_values else 0.0,
        }

    @classmethod
    def _ai_exit_readiness(cls, records: list[dict[str, Any]], recent: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = cls._learning_metrics(recent)
        criteria = {
            "min_recent_decisions": len(recent) >= 20,
            "success_rate_at_least_0_70": metrics["recommendation_success_rate"] >= 0.70,
            "human_override_rate_below_0_20": metrics["human_override_rate"] < 0.20,
            "repeat_error_rate_below_0_10": metrics["repeat_error_rate"] < 0.10,
            "critical_bad_release_zero": metrics["critical_bad_release_count"] == 0,
        }
        return {
            "ready_for_ai_observer_mode": bool(records) and all(criteria.values()),
            "criteria": criteria,
            "mode_recommendation": "observer_only" if bool(records) and all(criteria.values()) else "keep_meta_evaluator",
        }

    @classmethod
    def _ai_exit_readiness_trend(cls, records: list[dict[str, Any]], recent: list[dict[str, Any]]) -> dict[str, Any]:
        overall_metrics = cls._learning_metrics(records)
        recent_metrics = cls._learning_metrics(recent)
        overall = cls._ai_exit_readiness(records, records)
        recent_readiness = cls._ai_exit_readiness(records, recent)
        success_delta = round(recent_metrics["recommendation_success_rate"] - overall_metrics["recommendation_success_rate"], 4)
        override_delta = round(recent_metrics["human_override_rate"] - overall_metrics["human_override_rate"], 4)
        repeat_delta = round(recent_metrics["repeat_error_rate"] - overall_metrics["repeat_error_rate"], 4)

        if success_delta > 0 and override_delta <= 0 and repeat_delta <= 0:
            direction = "improving"
        elif success_delta < 0 or override_delta > 0 or repeat_delta > 0:
            direction = "regressing"
        else:
            direction = "flat"

        return {
            "overall": overall,
            "recent": recent_readiness,
            "window_size": len(recent),
            "delta": {
                "recommendation_success_rate": success_delta,
                "human_override_rate": override_delta,
                "repeat_error_rate": repeat_delta,
                "critical_bad_release_count": recent_metrics["critical_bad_release_count"] - overall_metrics["critical_bad_release_count"],
            },
            "direction": direction,
        }

    @staticmethod
    def _timeline(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            items.append(
                {
                    "index": index,
                    "run_id": record.get("run_id"),
                    "recorded_at": record.get("recorded_at"),
                    "decision": record.get("decision"),
                    "selected_candidate_id": record.get("selected_candidate_id"),
                    "selected_source_module": record.get("selected_source_module"),
                    "problem_layer": record.get("problem_layer"),
                    "outcome_status": record.get("outcome_status"),
                    "decision_useful": record.get("decision_useful"),
                    "human_override": record.get("human_override"),
                }
            )
        return items

    @staticmethod
    def _rate(records: list[dict[str, Any]], key: str) -> float:
        if not records:
            return 0.0
        return round(sum(1 for record in records if bool(record.get(key, False))) / len(records), 4)

    @staticmethod
    def _bool_or_none(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def apply_label(
        self,
        feedback_path: str | Path,
        *,
        decision_useful: bool | None = None,
        metrics_improved: bool | None = None,
        problem_layer_correct: bool | None = None,
        human_override: bool | None = None,
        wasted_run: bool | None = None,
        repeated_problem: bool | None = None,
        critical_bad_release: bool | None = None,
        label_source: str = "human",
        label_note: str = "",
    ) -> dict[str, Any]:
        """Apply a human outcome label to one feedback artifact."""
        path = Path(feedback_path)
        payload = read_json(path, expect_object=True)
        updates = {
            "decision_useful": decision_useful,
            "metrics_improved": metrics_improved,
            "problem_layer_correct": problem_layer_correct,
            "human_override": human_override,
            "wasted_run": wasted_run,
            "repeated_problem": repeated_problem,
            "critical_bad_release": critical_bad_release,
        }
        for key, value in updates.items():
            if value is not None:
                payload[key] = value
        payload["label_status"] = "human_labeled"
        payload["label_source"] = label_source or "human"
        payload["labeled_at"] = datetime.now().isoformat()
        if label_note:
            payload["label_note"] = label_note
        payload["outcome_label"] = Phase0OutcomeFeedbackBuilder._outcome_label(payload)
        if label_note:
            payload["outcome_label"]["label_note"] = label_note
        payload = validate_outcome_feedback(payload, source_path=path)
        write_json(path, payload)
        return payload

class Phase0OutcomeFeedbackBuilder:
    """Build a structured feedback object after an arbiter decision is written."""

    def __init__(
        self,
        run_id: str,
        contract_stage: str,
        contract_status: str,
        contract_path: str,
        run_root: str,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
    ):
        self.run_id = run_id
        self.contract_stage = contract_stage
        self.contract_status = contract_status
        self.contract_path = contract_path
        self.run_root = run_root
        self.metrics = metrics
        self.artifacts = artifacts

    def build(
        self,
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
        current_state: dict[str, Any],
        arbiter_decision: dict[str, Any],
        shared_decision_path: str,
        output_path: Path,
    ) -> dict[str, Any]:
        stage_name = self._shared_stage_name()
        can_proceed = bool(arbiter_decision.get("can_proceed", False))
        requires_review = bool(arbiter_decision.get("requires_human_review", False))
        outcome_status = "accepted" if can_proceed else "held_for_review"
        selected_candidate_id, selected_source_module, selected_problem_layer = self._selected_candidate_context(
            candidate_pool,
            arbiter_decision,
        )
        dominant_problem_layer = self._dominant_problem_layer(current_state)
        problem_layer = selected_problem_layer or dominant_problem_layer
        token_cost_estimate = self._token_cost_estimate(candidate_pool, arbiter_decision, report_data)
        decision_useful = self._preliminary_decision_useful(
            can_proceed=can_proceed,
            report_data=report_data,
            arbiter_decision=arbiter_decision,
        )

        payload = {
            "schema_version": 1,
            "feedback_id": f"{self.run_id}:{stage_name}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "decision_ref": str(output_path.parent / "arbiter_decision.json"),
            "state_ref": str(output_path.parent / "current_state.json"),
            "event_ref": self.contract_path,
            "run_id": self.run_id,
            "run_root": self.run_root,
            "contract_stage": self.contract_stage,
            "active_pack": current_state.get("active_pack", "unknown"),
            "decision": arbiter_decision.get("decision", "unknown"),
            "can_proceed": can_proceed,
            "requires_human_review": requires_review,
            "selected_candidate_id": selected_candidate_id,
            "selected_source_module": selected_source_module,
            "problem_layer": problem_layer,
            "dominant_problem_layer": dominant_problem_layer,
            "outcome_status": outcome_status,
            "human_override": False,
            "metrics_improved": None,
            "problem_layer_correct": None,
            "decision_useful": decision_useful,
            "wasted_run": False,
            "repeated_problem": False,
            "critical_bad_release": False,
            "token_cost_estimate": token_cost_estimate,
            "label_status": "auto_preliminary",
            "label_source": "runtime_default",
            "observed_metrics": self._observed_metrics(report_data),
            "observed_artifacts": self._observed_artifacts(shared_decision_path, output_path),
            "drift_vs_expectation": self._drift_vs_expectation(arbiter_decision, report_data),
            "lessons": self._lessons(arbiter_decision, report_data, candidate_pool),
            "update_targets": self._update_targets(can_proceed),
            "recorded_at": datetime.now().isoformat(),
        }
        payload["outcome_label"] = self._outcome_label(payload)
        payload = validate_outcome_feedback(payload, source_path=output_path)
        write_json(output_path, payload)
        return payload

    def _shared_stage_name(self) -> str:
        mapping = {
            "sfm_complete": "sfm",
            "train_complete": "train",
            "export_complete": "export",
        }
        return mapping.get(self.contract_stage, self.contract_stage)

    @staticmethod
    def _selected_candidate_context(
        candidate_pool: dict[str, Any],
        arbiter_decision: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None]:
        candidate_id = arbiter_decision.get("selected_candidate_id")
        if not candidate_id:
            return None, None, None
        for candidate in candidate_pool.get("candidates", []):
            if candidate.get("candidate_id") == candidate_id:
                return str(candidate_id), candidate.get("source_module"), candidate.get("problem_layer")
        return str(candidate_id), None, None

    @staticmethod
    def _dominant_problem_layer(current_state: dict[str, Any]) -> str | None:
        context = current_state.get("context", {}) or {}
        signal = context.get("problem_layer_signal", {}) or {}
        value = signal.get("dominant_layer")
        return str(value) if value else None

    def _observed_metrics(self, report_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_metrics": self.metrics,
            "report_flags": {
                "pointcloud_pass": report_data.get("pointcloud_pass"),
                "validation_ready": report_data.get("validation_ready"),
                "validation_pass": report_data.get("validation_pass"),
                "import_success": report_data.get("import_success"),
            },
            "recommendation": report_data.get("recommendation"),
        }

    def _observed_artifacts(self, shared_decision_path: str, output_path: Path) -> dict[str, Any]:
        return {
            "contract_artifacts": self.artifacts,
            "shared_decision": shared_decision_path,
            "phase0_report_json": str(output_path.parent / "phase0_report.json"),
            "phase0_report_md": str(output_path.parent / "PHASE0_FINAL_REPORT.md"),
            "candidate_pool_json": str(output_path.parent / "candidate_pool.json"),
            "decision_observability_json": str(output_path.parent / "observability.json"),
        }

    @staticmethod
    def _drift_vs_expectation(
        arbiter_decision: dict[str, Any],
        report_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        expected_action = (arbiter_decision.get("next_action") or {}).get("type", "unknown")
        recommendation = report_data.get("recommendation", "N/A")
        return [
            {
                "expected": expected_action,
                "observed": recommendation,
                "status": "needs_followup" if arbiter_decision.get("requires_human_review") else "aligned",
            }
        ]

    @staticmethod
    def _lessons(
        arbiter_decision: dict[str, Any],
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
    ) -> list[str]:
        lessons: list[str] = []
        reason = arbiter_decision.get("reason")
        if reason:
            lessons.append(str(reason))
        next_steps = report_data.get("next_steps", [])
        lessons.extend(str(item) for item in next_steps if item)
        if not lessons:
            lessons.append(f"{candidate_pool.get('candidate_count', 0)} candidates evaluated")
        return lessons

    @staticmethod
    def _update_targets(can_proceed: bool) -> list[str]:
        if can_proceed:
            return ["current_state_review", "experiment_history", "learning_curve"]
        return ["current_state_review", "experiment_history", "learning_curve", "human_label"]

    def _preliminary_decision_useful(
        self,
        *,
        can_proceed: bool,
        report_data: dict[str, Any],
        arbiter_decision: dict[str, Any],
    ) -> bool | None:
        if can_proceed:
            return True

        decision = str(arbiter_decision.get("decision", ""))
        stage_name = self._shared_stage_name()
        if stage_name == "sfm" and decision == "hold_train" and report_data.get("pointcloud_pass") is False:
            return True
        if (
            stage_name == "train"
            and decision == "hold_export"
            and report_data.get("validation_ready") is True
            and report_data.get("validation_pass") is False
        ):
            return True
        if (
            stage_name == "export"
            and decision == "hold_phase_close"
            and "import_success" in report_data
            and report_data.get("import_success") is False
        ):
            return True
        return None

    @staticmethod
    def _token_cost_estimate(
        candidate_pool: dict[str, Any],
        arbiter_decision: dict[str, Any],
        report_data: dict[str, Any],
    ) -> int:
        candidate_count = int(candidate_pool.get("candidate_count", len(candidate_pool.get("candidates", []))) or 0)
        text_size = len(str(arbiter_decision.get("reason", ""))) + len(str(report_data.get("recommendation", "")))
        return int(350 + candidate_count * 180 + min(text_size // 4, 2000))

    @staticmethod
    def _outcome_label(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "human_override": payload.get("human_override"),
            "metrics_improved": payload.get("metrics_improved"),
            "problem_layer_correct": payload.get("problem_layer_correct"),
            "decision_useful": payload.get("decision_useful"),
            "wasted_run": payload.get("wasted_run"),
            "repeated_problem": payload.get("repeated_problem"),
            "critical_bad_release": payload.get("critical_bad_release"),
            "label_status": payload.get("label_status"),
            "label_source": payload.get("label_source"),
        }
