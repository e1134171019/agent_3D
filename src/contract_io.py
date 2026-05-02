"""Shared JSON and contract helpers for the decision layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


JSON_ENCODINGS = ("utf-8", "utf-8-sig", "cp950", "mbcs")
REQUIRED_STAGE_CONTRACT_KEYS = ("schema_version", "timestamp", "run_id", "run_root", "stage", "status")
DICT_STAGE_CONTRACT_KEYS = ("artifacts", "metrics", "params")
REQUIRED_CANDIDATE_KEYS = (
    "candidate_id",
    "source_module",
    "scope",
    "proposal_type",
    "title",
    "rationale",
    "params",
    "expected_gain",
    "expected_risk",
    "estimated_cost",
    "blocked_by",
    "evidence",
    "confidence",
)
REQUIRED_CANDIDATE_POOL_KEYS = (
    "schema_version",
    "timestamp",
    "run_id",
    "contract_stage",
    "candidate_count",
    "candidates",
)
REQUIRED_CURRENT_STATE_KEYS = (
    "schema_version",
    "state_id",
    "phase",
    "active_pack",
    "current_best",
    "next_focus",
    "allowed_actions",
    "blocked_actions",
    "blacklist",
    "source_docs",
    "updated_at",
)
REQUIRED_ARBITER_DECISION_KEYS = (
    "schema_version",
    "decision_id",
    "state_ref",
    "event_ref",
    "selected_candidate_id",
    "rejected_candidate_ids",
    "decision",
    "reason",
    "next_action",
    "can_proceed",
    "requires_human_review",
    "written_at",
)
REQUIRED_SHARED_DECISION_KEYS = (
    "schema_version",
    "timestamp",
    "run_id",
    "source_contract",
    "source_stage",
    "source_status",
    "run_root",
    "decision_stage",
    "decision_gate",
    "decision",
    "can_proceed",
    "recommendation",
    "next_steps",
    "metrics",
    "arbiter",
    "state",
    "reports",
)
REQUIRED_OUTCOME_FEEDBACK_KEYS = (
    "schema_version",
    "feedback_id",
    "decision_ref",
    "run_id",
    "outcome_status",
    "observed_metrics",
    "observed_artifacts",
    "drift_vs_expectation",
    "lessons",
    "update_targets",
    "recorded_at",
)


class ContractValidationError(ValueError):
    """Raised when a production-to-decision contract is structurally invalid."""


def _source_suffix(source_path: str | Path = "") -> str:
    if not source_path:
        return ""
    return f": {source_path}"


def _require_object(payload: Any, label: str, source_path: str | Path = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractValidationError(f"{label} must be an object{_source_suffix(source_path)}")
    return dict(payload)


def _require_keys(
    payload: dict[str, Any],
    required_keys: tuple[str, ...],
    label: str,
    source_path: str | Path = "",
) -> None:
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise ContractValidationError(f"{label} missing required keys {missing}{_source_suffix(source_path)}")


def _require_dict_fields(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    label: str,
    source_path: str | Path = "",
) -> None:
    for key in field_names:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise ContractValidationError(f"{label} field '{key}' must be an object{_source_suffix(source_path)}")


def _require_list_fields(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    label: str,
    source_path: str | Path = "",
) -> None:
    for key in field_names:
        value = payload.get(key)
        if not isinstance(value, list):
            raise ContractValidationError(f"{label} field '{key}' must be a list{_source_suffix(source_path)}")


def _require_bool_fields(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    label: str,
    source_path: str | Path = "",
) -> None:
    for key in field_names:
        value = payload.get(key)
        if not isinstance(value, bool):
            raise ContractValidationError(f"{label} field '{key}' must be a boolean{_source_suffix(source_path)}")


def _require_non_empty_string_fields(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    label: str,
    source_path: str | Path = "",
) -> None:
    for key in field_names:
        if not str(payload.get(key, "")).strip():
            raise ContractValidationError(f"{label} field '{key}' cannot be empty{_source_suffix(source_path)}")


def read_json(path: str | Path, *, expect_object: bool = True) -> Any:
    """Read JSON with the encodings used by Windows-side production artifacts."""
    path = Path(path)
    last_error: Exception | None = None
    for encoding in JSON_ENCODINGS:
        try:
            payload = json.loads(path.read_text(encoding=encoding))
            if expect_object and not isinstance(payload, dict):
                raise ContractValidationError(f"JSON root must be an object: {path}")
            return payload
        except Exception as exc:
            last_error = exc
    raise last_error if last_error is not None else ValueError(f"Unable to parse JSON: {path}")


def write_json(path: str | Path, payload: Any) -> Path:
    """Write stable UTF-8 JSON and create the parent directory if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read history files stored either as JSON object/list or as JSON Lines."""
    path = Path(path)
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        return records

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def normalize_stage_contract(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate and normalize the minimum production event contract shape."""
    normalized = _require_object(payload, "Stage contract", source_path)
    _require_keys(normalized, REQUIRED_STAGE_CONTRACT_KEYS, "Stage contract", source_path)

    for key in DICT_STAGE_CONTRACT_KEYS:
        value = normalized.get(key, {})
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise ContractValidationError(f"Stage contract field '{key}' must be an object: {source_path}")
        normalized[key] = value

    _require_non_empty_string_fields(normalized, ("run_id", "run_root", "stage", "status"), "Stage contract", source_path)

    return normalized


def normalize_candidate(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate and normalize one strategy candidate."""
    normalized = _require_object(payload, "Candidate", source_path)
    _require_keys(normalized, REQUIRED_CANDIDATE_KEYS, "Candidate", source_path)
    _require_dict_fields(normalized, ("params", "evidence"), "Candidate", source_path)
    _require_list_fields(normalized, ("blocked_by",), "Candidate", source_path)
    _require_non_empty_string_fields(
        normalized,
        ("candidate_id", "source_module", "scope", "proposal_type"),
        "Candidate",
        source_path,
    )

    try:
        normalized["confidence"] = float(normalized["confidence"])
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"Candidate field 'confidence' must be numeric{_source_suffix(source_path)}") from exc

    if not 0.0 <= normalized["confidence"] <= 1.0:
        raise ContractValidationError(f"Candidate field 'confidence' must be between 0 and 1{_source_suffix(source_path)}")

    return normalized


def validate_candidate_pool(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate the per-run candidate pool audit artifact."""
    normalized = _require_object(payload, "Candidate pool", source_path)
    _require_keys(normalized, REQUIRED_CANDIDATE_POOL_KEYS, "Candidate pool", source_path)
    _require_non_empty_string_fields(normalized, ("run_id", "contract_stage"), "Candidate pool", source_path)
    candidates = normalized.get("candidates")
    if not isinstance(candidates, list):
        raise ContractValidationError(f"Candidate pool field 'candidates' must be a list{_source_suffix(source_path)}")

    normalized["candidates"] = [
        normalize_candidate(candidate, source_path=f"{source_path}#candidates[{index}]")
        for index, candidate in enumerate(candidates)
    ]
    if normalized.get("candidate_count") != len(normalized["candidates"]):
        raise ContractValidationError(
            f"Candidate pool field 'candidate_count' must match candidates length{_source_suffix(source_path)}"
        )
    return normalized


def validate_current_state(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate the active decision-cycle state snapshot."""
    normalized = _require_object(payload, "Current state", source_path)
    _require_keys(normalized, REQUIRED_CURRENT_STATE_KEYS, "Current state", source_path)
    _require_non_empty_string_fields(
        normalized,
        ("state_id", "phase", "active_pack", "current_best", "next_focus", "updated_at"),
        "Current state",
        source_path,
    )
    _require_list_fields(
        normalized,
        ("allowed_actions", "blocked_actions", "blacklist", "source_docs"),
        "Current state",
        source_path,
    )
    if "context" in normalized and not isinstance(normalized["context"], dict):
        raise ContractValidationError(f"Current state field 'context' must be an object{_source_suffix(source_path)}")
    return normalized


def validate_arbiter_decision(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate the single formal arbiter decision."""
    normalized = _require_object(payload, "Arbiter decision", source_path)
    _require_keys(normalized, REQUIRED_ARBITER_DECISION_KEYS, "Arbiter decision", source_path)
    _require_non_empty_string_fields(
        normalized,
        ("decision_id", "state_ref", "event_ref", "decision", "reason", "written_at"),
        "Arbiter decision",
        source_path,
    )
    _require_dict_fields(normalized, ("next_action",), "Arbiter decision", source_path)
    _require_list_fields(normalized, ("rejected_candidate_ids",), "Arbiter decision", source_path)
    _require_bool_fields(normalized, ("can_proceed", "requires_human_review"), "Arbiter decision", source_path)
    if normalized.get("selected_candidate_id") is not None and not str(normalized["selected_candidate_id"]).strip():
        raise ContractValidationError(
            f"Arbiter decision field 'selected_candidate_id' cannot be blank{_source_suffix(source_path)}"
        )
    return normalized


def validate_shared_decision(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate the production-facing latest_*_decision.json payload."""
    normalized = _require_object(payload, "Shared decision", source_path)
    _require_keys(normalized, REQUIRED_SHARED_DECISION_KEYS, "Shared decision", source_path)
    _require_non_empty_string_fields(
        normalized,
        (
            "timestamp",
            "run_id",
            "source_contract",
            "source_stage",
            "source_status",
            "run_root",
            "decision_stage",
            "decision_gate",
            "decision",
            "recommendation",
        ),
        "Shared decision",
        source_path,
    )
    _require_dict_fields(normalized, ("metrics", "arbiter", "state", "reports"), "Shared decision", source_path)
    _require_list_fields(normalized, ("next_steps",), "Shared decision", source_path)
    _require_bool_fields(normalized, ("can_proceed",), "Shared decision", source_path)
    _require_dict_fields(normalized["arbiter"], ("next_action",), "Shared decision arbiter", source_path)
    _require_list_fields(normalized["arbiter"], ("rejected_candidate_ids",), "Shared decision arbiter", source_path)
    _require_bool_fields(normalized["arbiter"], ("requires_human_review",), "Shared decision arbiter", source_path)
    return normalized


def validate_outcome_feedback(payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
    """Validate the feedback object used for future candidate ranking."""
    normalized = _require_object(payload, "Outcome feedback", source_path)
    _require_keys(normalized, REQUIRED_OUTCOME_FEEDBACK_KEYS, "Outcome feedback", source_path)
    _require_non_empty_string_fields(
        normalized,
        ("feedback_id", "decision_ref", "run_id", "outcome_status", "recorded_at"),
        "Outcome feedback",
        source_path,
    )
    _require_dict_fields(normalized, ("observed_metrics", "observed_artifacts"), "Outcome feedback", source_path)
    _require_list_fields(
        normalized,
        ("drift_vs_expectation", "lessons", "update_targets"),
        "Outcome feedback",
        source_path,
    )
    return normalized
