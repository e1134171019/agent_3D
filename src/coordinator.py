"""Contract-driven Phase0Coordinator for the decision layer."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.contract_io import normalize_stage_contract, read_json, validate_shared_decision, write_json
from src.outcome_feedback import OutcomeFeedbackHistory


ARTIFACT_ALIASES: dict[str, tuple[str, ...]] = {
    "pointcloud_report": ("pointcloud_validation_report", "pointcloud_report", "report"),
    "training_stats": ("stats_json", "val_stats", "validation_stats"),
    "checkpoint": ("checkpoint", "ckpt"),
    "ply_file": ("ply_file", "ply"),
    "data_dir": ("data_dir", "colmap_dir"),
}

ARTIFACT_FALLBACKS: dict[str, Path] = {
    "pointcloud_report": Path("reports") / "pointcloud_validation_report.json",
    "training_stats": Path("3DGS_models") / "stats" / "val_step29999.json",
    "checkpoint": Path("3DGS_models") / "ckpts" / "ckpt_29999_rank0.pt",
    "ply_file": Path("3DGS_models") / "ply" / "point_cloud_final.ply",
    "data_dir": Path("SfM_models") / "sift" / "sparse",
}


@dataclass
class DecisionLogEntry:
    timestamp: str
    stage: str
    proposal_id: str
    proposal_text: str
    evaluation: dict[str, Any]
    action: str
    action_reason: str
    event_emitted: str | None = None
    problem_layer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "stage": self.stage,
            "proposal_id": self.proposal_id,
            "proposal_text": self.proposal_text,
            "evaluation": self.evaluation,
            "action": self.action,
            "action_reason": self.action_reason,
            "event_emitted": self.event_emitted,
            "problem_layer": self.problem_layer,
        }


class EventBus:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def emit(self, event_name: str, data: dict[str, Any] | None = None) -> None:
        payload = {
            "sequence": len(self.events) + 1,
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            "data": data or {},
        }
        self.events.append(payload)
        print(f"[EventBus] {event_name}")

    def snapshot(self) -> dict[str, Any]:
        event_counts = Counter(item.get("event", "unknown") for item in self.events)
        first_timestamp = self.events[0]["timestamp"] if self.events else None
        last_timestamp = self.events[-1]["timestamp"] if self.events else None
        return {
            "event_count": len(self.events),
            "event_names": [item.get("event", "unknown") for item in self.events],
            "event_counts": dict(event_counts),
            "first_timestamp": first_timestamp,
            "last_timestamp": last_timestamp,
            "time_span_ms": _elapsed_ms(first_timestamp, last_timestamp),
            "trace": list(self.events),
        }


class ArtifactResolver:
    """Resolve production artifact paths from contract aliases and stable fallbacks."""

    def __init__(self, artifacts: dict[str, Any], run_root: Path):
        self.artifacts = artifacts
        self.run_root = run_root

    def resolve(self, artifact_name: str) -> Path:
        for alias in ARTIFACT_ALIASES[artifact_name]:
            raw = self.artifacts.get(alias)
            if raw:
                return Path(raw)
        return self.run_root / ARTIFACT_FALLBACKS[artifact_name]


class Phase0ReportGenerator:
    """Generate the formal phase0 report consumed by state, arbiter, and shared decisions."""

    @staticmethod
    def generate(
        *,
        run_id: str,
        contract_stage: str,
        contract_status: str,
        shared_stage_name: str,
        pack_result: dict[str, Any],
        validation_report: dict[str, Any],
        validation_ready: bool,
        decision_log_count: int,
    ) -> dict[str, Any]:
        pointcloud_pass = bool(pack_result.get("pointcloud_ready", False))
        validation_pass = bool(validation_report.get("overall_pass", False))
        import_success = False
        recommendation, next_steps = Phase0ReportGenerator._recommend(
            shared_stage_name=shared_stage_name,
            pointcloud_pass=pointcloud_pass,
            validation_pass=validation_pass,
            import_success=import_success,
        )
        return {
            "timestamp": datetime.now().isoformat(),
            "run_id": run_id,
            "contract_stage": contract_stage,
            "contract_status": contract_status,
            "pointcloud_pass": pointcloud_pass,
            "validation_ready": validation_ready,
            "validation_pass": validation_pass,
            "import_success": import_success,
            "recommendation": recommendation,
            "next_steps": next_steps,
            "pack_result": pack_result,
            "validation_report": validation_report,
            "decision_log_count": decision_log_count,
        }

    @staticmethod
    def _recommend(
        *,
        shared_stage_name: str,
        pointcloud_pass: bool,
        validation_pass: bool,
        import_success: bool,
    ) -> tuple[str, list[str]]:
        if shared_stage_name == "sfm":
            if pointcloud_pass:
                return "proceed_to_train", ["start_3dgs_training"]
            return "hold_train", ["recover_sfm_inputs"]
        if shared_stage_name == "train":
            if validation_pass:
                return "proceed_to_export", ["export_ply"]
            return "hold_export", ["review_training_quality"]
        if shared_stage_name == "export":
            if import_success:
                return "export_verified", ["close_phase"]
            return "hold_phase_close", ["review_export_result"]
        if validation_pass:
            return "proceed", ["review_current_stage"]
        return "hold", ["review_current_stage"]


def _read_json(path: Path) -> dict[str, Any]:
    return read_json(path, expect_object=True)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return slug or "unknown"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _elapsed_ms(start: str | None, end: str | None) -> int | None:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    delta = end_dt - start_dt
    return max(int(delta.total_seconds() * 1000), 0)


class Phase0Coordinator:
    """Consume production contracts and emit decision-layer reports."""

    def __init__(
        self,
        production_path: str,
        events_root: str,
        output_root: str,
        contract_path: str,
        unity_project_path: str | None = None,
        decisions_root: str | None = None,
    ):
        self.production_path = Path(production_path)
        self.events_root = Path(events_root)
        self.output_root = Path(output_root)
        self.contract_path = Path(contract_path)
        self.decisions_root = Path(decisions_root) if decisions_root else (self.events_root.parent / "agent_decisions")
        self.contract = normalize_stage_contract(
            _read_json(self.contract_path),
            source_path=self.contract_path,
        )
        self.artifacts = self.contract.get("artifacts", {}) or {}
        self.metrics = self.contract.get("metrics", {}) or {}
        self.params = self.contract.get("params", {}) or {}
        self.run_id = self.contract.get("run_id") or self.contract_path.stem
        self.contract_stage = self.contract.get("stage") or "unknown_stage"
        self.contract_status = self.contract.get("status") or "unknown"
        self.run_root = Path(self.contract.get("run_root")) if self.contract.get("run_root") else self.production_path
        self.output_path = self.output_root / _safe_slug(self.run_id) / _safe_slug(self.contract_stage)
        if self.output_path.exists():
            shutil.rmtree(self.output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.decisions_root.mkdir(parents=True, exist_ok=True)
        self.unity_project_path = Path(unity_project_path) if unity_project_path else None
        self.event_bus = EventBus()
        self.decision_log: list[DecisionLogEntry] = []
        self.artifact_resolver = ArtifactResolver(self.artifacts, self.run_root)

        self.pointcloud_report_path = self.artifact_resolver.resolve("pointcloud_report")
        self.training_stats_path = self.artifact_resolver.resolve("training_stats")
        self.ckpt_path = self.artifact_resolver.resolve("checkpoint")
        self.ply_path = self.artifact_resolver.resolve("ply_file")
        self.data_dir = self.artifact_resolver.resolve("data_dir")

    def _append_decision(
        self,
        stage: str,
        proposal_id: str,
        proposal_text: str,
        evaluation: dict[str, Any],
        action: str,
        action_reason: str,
        event_emitted: str | None = None,
        problem_layer: str | None = None,
    ) -> None:
        self.decision_log.append(
            DecisionLogEntry(
                timestamp=datetime.now().isoformat(),
                stage=stage,
                proposal_id=proposal_id,
                proposal_text=proposal_text,
                evaluation=evaluation,
                action=action,
                action_reason=action_reason,
                event_emitted=event_emitted,
                problem_layer=problem_layer,
            )
        )

    def _write_contract_context(self) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "contract_path": str(self.contract_path),
            "run_id": self.run_id,
            "contract_stage": self.contract_stage,
            "contract_status": self.contract_status,
            "run_root": str(self.run_root),
            "resolved_paths": {
                "pointcloud_report": str(self.pointcloud_report_path),
                "training_stats": str(self.training_stats_path),
                "checkpoint": str(self.ckpt_path),
                "ply": str(self.ply_path),
                "data_dir": str(self.data_dir),
            },
            "metrics": self.metrics,
            "params": self.params,
        }
        write_json(self.output_path / "contract_context.json", payload)

    def _save_decision_log(self) -> None:
        payload = [entry.to_dict() for entry in self.decision_log]
        write_json(self.output_path / "phase0_decisions.log", payload)

    def _load_or_write_phase0_report(self, pack_result: dict[str, Any]) -> dict[str, Any]:
        report_path = self.output_path / "phase0_report.json"
        if report_path.exists():
            return _read_json(report_path)

        validation_report_path = self.output_path / "validation_report.json"
        validation_report = _read_json(validation_report_path) if validation_report_path.exists() else {}
        validation_ready = validation_report_path.exists()
        payload = Phase0ReportGenerator.generate(
            run_id=self.run_id,
            contract_stage=self.contract_stage,
            contract_status=self.contract_status,
            shared_stage_name=self._shared_stage_name(),
            pack_result=pack_result,
            validation_report=validation_report,
            validation_ready=validation_ready,
            decision_log_count=len(self.decision_log),
        )
        write_json(report_path, payload)
        return payload

    def _write_candidate_pool(self) -> dict[str, Any]:
        from src.candidate_pool import Phase0CandidatePoolBuilder

        builder = Phase0CandidatePoolBuilder(
            run_id=self.run_id,
            contract_stage=self.contract_stage,
        )
        return builder.build(
            decision_log=[entry.to_dict() for entry in self.decision_log],
            output_path=self.output_path / "candidate_pool.json",
        )

    def _write_current_state(
        self,
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
    ) -> dict[str, Any]:
        from src.current_state import Phase0CurrentStateBuilder

        builder = Phase0CurrentStateBuilder(
            run_id=self.run_id,
            contract_stage=self.contract_stage,
            contract_status=self.contract_status,
            source_contract=str(self.contract_path),
            run_root=str(self.run_root),
        )
        return builder.build(
            report_data=report_data,
            candidate_pool=candidate_pool,
            output_path=self.output_path / "current_state.json",
        )

    def _shared_stage_name(self) -> str:
        mapping = {
            "sfm_complete": "sfm",
            "train_complete": "train",
            "export_complete": "export",
        }
        return mapping.get(self.contract_stage, _safe_slug(self.contract_stage))

    def _write_shared_decision(self, arbiter_decision: dict[str, Any]) -> Path:
        from src.shared_decision_mapper import Phase0SharedDecisionMapper

        report_path = self.output_path / "phase0_report.json"
        report_data = _read_json(report_path) if report_path.exists() else {}
        mapper = Phase0SharedDecisionMapper(
            run_id=self.run_id,
            source_contract=str(self.contract_path),
            source_stage=self.contract_stage,
            source_status=self.contract_status,
            run_root=str(self.run_root),
            metrics=self.metrics,
        )
        payload = mapper.build(
            report_data=report_data,
            arbiter_decision=arbiter_decision,
            reports={
                "phase0_report_json": str(report_path),
                "phase0_report_md": str(self.output_path / "PHASE0_FINAL_REPORT.md"),
                "current_state_json": str(self.output_path / "current_state.json"),
                "candidate_pool_json": str(self.output_path / "candidate_pool.json"),
                "arbiter_decision_json": str(self.output_path / "arbiter_decision.json"),
                "pointcloud_validation_report": str(self.output_path / "pointcloud_validation_report.json"),
                "validation_report": str(self.output_path / "validation_report.json"),
                "recovery_advice": str(self.output_path / "recovery_advice.json"),
                "observability_json": str(self.output_path / "observability.json"),
            },
        )
        payload["timestamp"] = datetime.now().isoformat()

        payload = validate_shared_decision(payload, source_path=self.decisions_root)
        stage_name = payload["decision_stage"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        decision_file = self.decisions_root / f"{timestamp}_{stage_name}_decision.json"
        latest_file = self.decisions_root / f"latest_{stage_name}_decision.json"
        write_json(decision_file, payload)
        write_json(latest_file, payload)
        return latest_file

    def _write_outcome_feedback(
        self,
        report_data: dict[str, Any],
        candidate_pool: dict[str, Any],
        current_state: dict[str, Any],
        arbiter_decision: dict[str, Any],
        shared_decision_path: Path,
    ) -> dict[str, Any]:
        from src.outcome_feedback import Phase0OutcomeFeedbackBuilder

        builder = Phase0OutcomeFeedbackBuilder(
            run_id=self.run_id,
            contract_stage=self.contract_stage,
            contract_status=self.contract_status,
            contract_path=str(self.contract_path),
            run_root=str(self.run_root),
            metrics=self.metrics,
            artifacts=self.artifacts,
        )
        feedback = builder.build(
            report_data=report_data,
            candidate_pool=candidate_pool,
            current_state=current_state,
            arbiter_decision=arbiter_decision,
            shared_decision_path=str(shared_decision_path),
            output_path=self.output_path / "outcome_feedback.json",
        )
        from src.outcome_feedback import OutcomeFeedbackHistory

        history = OutcomeFeedbackHistory(self.output_root)
        learning_curve = history.write_learning_curve(self.output_path / "learning_curve.json")
        return feedback, learning_curve

    def _build_history_signal(self) -> dict[str, Any]:
        history = OutcomeFeedbackHistory(self.output_root)
        return history.build_learning_curve(exclude_path=self.output_path / "outcome_feedback.json")

    def _write_observability_snapshot(
        self,
        *,
        candidate_pool: dict[str, Any],
        current_state: dict[str, Any],
        arbiter_decision: dict[str, Any],
        outcome_feedback: dict[str, Any],
        learning_curve: dict[str, Any],
    ) -> dict[str, Any]:
        decision_latency_ms = _elapsed_ms(self.contract.get("timestamp"), arbiter_decision.get("written_at"))
        candidate_count = int(candidate_pool.get("candidate_count", len(candidate_pool.get("candidates", []))) or 0)
        retained_candidate_count = sum(
            1 for entry in self.decision_log if str(entry.action).strip().lower() != "skipped"
        )
        candidate_recall = round(retained_candidate_count / len(self.decision_log), 4) if self.decision_log else None
        arbiter_correctness = self._score_from_label(outcome_feedback.get("decision_useful"))
        problem_layer_accuracy = self._score_from_label(outcome_feedback.get("problem_layer_correct"))
        ai_exit_trend = learning_curve.get("ai_exit_readiness_trend", {}) or {}
        ai_exit_readiness = learning_curve.get("ai_exit_readiness", {}) or {}

        alerts: list[str] = []
        if decision_latency_ms is None:
            alerts.append("decision_latency_unavailable")
        elif decision_latency_ms > 60000:
            alerts.append("decision_latency_high")
        if candidate_recall is None:
            alerts.append("candidate_recall_unavailable")
        elif candidate_recall < 1.0:
            alerts.append("candidate_recall_below_full")
        if arbiter_correctness is None:
            alerts.append("arbiter_correctness_unlabeled")
        if problem_layer_accuracy is None:
            alerts.append("problem_layer_accuracy_unlabeled")
        if not ai_exit_readiness.get("ready_for_ai_observer_mode", False):
            alerts.append("keep_meta_evaluator")

        payload = {
            "schema_version": 1,
            "generated_at": datetime.now().isoformat(),
            "run_id": self.run_id,
            "contract_stage": self.contract_stage,
            "contract_status": self.contract_status,
            "decision_latency_ms": decision_latency_ms,
            "candidate_count": candidate_count,
            "retained_candidate_count": retained_candidate_count,
            "candidate_recall": candidate_recall,
            "arbiter_correctness": arbiter_correctness,
            "problem_layer_accuracy": problem_layer_accuracy,
            "ai_exit_readiness_trend": ai_exit_trend,
            "ai_exit_readiness": ai_exit_readiness,
            "event_trace": self.event_bus.snapshot(),
            "candidate_summary": {
                "selected_candidate_id": arbiter_decision.get("selected_candidate_id"),
                "selected_source_module": outcome_feedback.get("selected_source_module"),
                "dominant_problem_layer": outcome_feedback.get("dominant_problem_layer"),
                "decision": arbiter_decision.get("decision"),
                "requires_human_review": arbiter_decision.get("requires_human_review"),
            },
            "observed_links": {
                "current_state": str(self.output_path / "current_state.json"),
                "arbiter_decision": str(self.output_path / "arbiter_decision.json"),
                "outcome_feedback": str(self.output_path / "outcome_feedback.json"),
                "learning_curve": str(self.output_path / "learning_curve.json"),
            },
            "alerts": alerts,
        }
        write_json(self.output_path / "observability.json", payload)
        return payload

    @staticmethod
    def _score_from_label(value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        return None

    def run(self) -> dict[str, Any]:
        from src.arbiter import Phase0Arbiter
        from src.map_building_pack import MapBuildingPackRunner

        self._write_contract_context()

        print("\n" + "=" * 68)
        print("Phase-0 Decision Loop")
        print("=" * 68)
        print(f"run_id:   {self.run_id}")
        print(f"stage:    {self.contract_stage} ({self.contract_status})")
        print(f"run_root: {self.run_root}")
        print(f"output:   {self.output_path}")

        pack_runner = MapBuildingPackRunner(self)
        pack_result = pack_runner.run()
        self._save_decision_log()
        candidate_pool = self._write_candidate_pool()
        report_data = self._load_or_write_phase0_report(pack_result)
        current_state = self._write_current_state(
            report_data=report_data,
            candidate_pool=candidate_pool,
        )
        history_signal = self._build_history_signal()
        arbiter = Phase0Arbiter(
            run_id=self.run_id,
            contract_stage=self.contract_stage,
            contract_path=str(self.contract_path),
            run_root=str(self.run_root),
        )
        arbiter_decision = arbiter.decide(
            current_state=current_state,
            report_data=report_data,
            candidate_pool=candidate_pool,
            state_ref=str(self.output_path / "current_state.json"),
            output_path=self.output_path / "arbiter_decision.json",
            history_signal=history_signal,
        )
        shared_decision = self._write_shared_decision(arbiter_decision=arbiter_decision)
        outcome_feedback, learning_curve = self._write_outcome_feedback(
            report_data=report_data,
            candidate_pool=candidate_pool,
            current_state=current_state,
            arbiter_decision=arbiter_decision,
            shared_decision_path=shared_decision,
        )
        self._write_observability_snapshot(
            candidate_pool=candidate_pool,
            current_state=current_state,
            arbiter_decision=arbiter_decision,
            outcome_feedback=outcome_feedback,
            learning_curve=learning_curve,
        )

        print("\n" + "=" * 68)
        print("Phase-0 Decision Loop Complete")
        print("=" * 68 + "\n")

        return {
            "run_id": self.run_id,
            "stage": self.contract_stage,
            "output_root": str(self.output_path),
            "report_json": str(self.output_path / "phase0_report.json"),
            "report_md": str(self.output_path / "PHASE0_FINAL_REPORT.md"),
            "current_state_json": str(self.output_path / "current_state.json"),
            "candidate_pool_json": str(self.output_path / "candidate_pool.json"),
            "arbiter_decision_json": str(self.output_path / "arbiter_decision.json"),
            "outcome_feedback_json": str(self.output_path / "outcome_feedback.json"),
            "learning_curve_json": str(self.output_path / "learning_curve.json"),
            "observability_json": str(self.output_path / "observability.json"),
            "shared_decision": str(shared_decision),
        }






