"""Offline PyTorch decision model built from outcome feedback artifacts.

This module is intentionally kept outside the formal 6-core runtime.
It is a learning adapter for experimentation, not the formal arbiter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import torch
from torch import nn

from src.outcome_feedback import OutcomeFeedbackHistory


DECISION_VOCAB = ("proceed_to_export", "hold_export", "hold_phase_close", "retry", "switch_strategy", "unknown")
SOURCE_MODULE_VOCAB = ("MapValidator", "ProductionParamGate", "PointCloudValidator", "unknown")
PROBLEM_LAYER_VOCAB = ("data", "parameter", "framework", "unknown")
STAGE_VOCAB = ("sfm_complete", "train_complete", "export_complete", "unknown")
RUN_ROLE_VOCAB = ("benchmark", "unity_candidate", "failed_probe", "unknown")
ISSUE_TYPE_VOCAB = ("parameter", "framework", "export", "unity_render", "data", "mixed", "unknown")
UNITY_RESULT_VOCAB = ("not_tested", "candidate", "visual_fail", "pass", "unknown")
FRAMEWORK_VOCAB = ("gsplat", "scaffold_gs", "unknown")
PROBE_STATUS_VOCAB = ("prepared", "trained", "reviewed", "setup_blocked", "unknown")


def _one_hot(value: str, vocab: tuple[str, ...]) -> list[float]:
    normalized = value if value in vocab else "unknown"
    return [1.0 if item == normalized else 0.0 for item in vocab]


def _bool_feature(value: Any) -> float:
    return 1.0 if bool(value) else 0.0


def _float_feature(value: Any, *, default: float = 0.0, scale: float = 1.0) -> float:
    try:
        return float(value) / scale
    except (TypeError, ValueError):
        return default


def _map_issue_type_to_problem_layer(issue_type: Any) -> str:
    """Project broader offline issue types into the formal runtime problem-layer space."""
    normalized = str(issue_type or "unknown")
    if normalized in PROBLEM_LAYER_VOCAB:
        return normalized
    mapping = {
        "export": "framework",
        "unity_render": "framework",
        "mixed": "unknown",
        "unknown": "unknown",
    }
    return mapping.get(normalized, "unknown")


def _sample_weight_from_teacher_labels(teacher_labels: dict[str, Any] | None) -> float:
    """Turn teacher confidence into a bounded sample weight for offline training."""
    if not teacher_labels:
        return 1.0
    confidence = teacher_labels.get("confidence")
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 1.0
    return max(0.1, min(value, 1.0))


def _probe_context(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("probe_context", {})
    return payload if isinstance(payload, dict) else {}


def _build_probe_context_vector(record: dict[str, Any]) -> list[float]:
    context = _probe_context(record)
    framework_name = str(context.get("framework_name", record.get("framework_name", "unknown")))
    probe_status = str(context.get("probe_status", record.get("probe_status", "unknown")))
    vector: list[float] = []
    vector.extend(_one_hot(framework_name, FRAMEWORK_VOCAB))
    vector.extend(_one_hot(probe_status, PROBE_STATUS_VOCAB))
    return vector


def _derive_backfill_runtime_bools(record: dict[str, Any]) -> list[float]:
    """Project run-level backfill facts into conservative runtime-style boolean hints."""
    unity_result = str(record.get("unity_result", "unknown"))
    role = str(record.get("role", "unknown"))
    issue_type = str(record.get("issue_type", "unknown"))

    can_proceed = unity_result in ("candidate", "pass")
    requires_human_review = role == "benchmark" or unity_result in ("visual_fail", "unknown")
    human_override = False
    wasted_run = role == "failed_probe" and unity_result in ("visual_fail", "not_tested", "unknown")
    repeated_problem = issue_type in ("parameter", "mixed") and unity_result in ("visual_fail", "not_tested", "unknown")
    critical_bad_release = False

    return [
        _bool_feature(can_proceed),
        _bool_feature(requires_human_review),
        _bool_feature(human_override),
        _bool_feature(wasted_run),
        _bool_feature(repeated_problem),
        _bool_feature(critical_bad_release),
    ]


def build_teacher_feature_vector(teacher_labels: dict[str, Any] | None) -> list[float]:
    """Convert teacher semantic labels into a stable numeric vector."""
    if not teacher_labels:
        teacher_labels = {}
    vector: list[float] = []
    vector.extend(_one_hot(str(teacher_labels.get("role", "unknown")), RUN_ROLE_VOCAB))
    vector.extend(_one_hot(str(teacher_labels.get("issue_type", "unknown")), ISSUE_TYPE_VOCAB))
    vector.extend(_one_hot(str(teacher_labels.get("unity_result", "unknown")), UNITY_RESULT_VOCAB))
    return vector


def feature_vector_dim() -> int:
    return (
        10
        + len(DECISION_VOCAB)
        + len(SOURCE_MODULE_VOCAB)
        + len(PROBLEM_LAYER_VOCAB)
        + len(STAGE_VOCAB)
        + len(FRAMEWORK_VOCAB)
        + len(PROBE_STATUS_VOCAB)
    )


def augmented_feature_vector_dim() -> int:
    return feature_vector_dim() + len(RUN_ROLE_VOCAB) + len(ISSUE_TYPE_VOCAB) + len(UNITY_RESULT_VOCAB)


def build_feature_vector(record: dict[str, Any]) -> list[float]:
    """Convert one outcome feedback record into a structured numeric vector."""
    metrics = record.get("observed_metrics", {}).get("contract_metrics", {})
    vector: list[float] = [
        _float_feature(metrics.get("psnr"), scale=50.0),
        _float_feature(metrics.get("ssim")),
        _float_feature(metrics.get("lpips")),
        _float_feature(metrics.get("num_gs"), scale=1_000_000.0),
        _bool_feature(record.get("can_proceed")),
        _bool_feature(record.get("requires_human_review")),
        _bool_feature(record.get("human_override")),
        _bool_feature(record.get("wasted_run")),
        _bool_feature(record.get("repeated_problem")),
        _bool_feature(record.get("critical_bad_release")),
    ]
    vector.extend(_one_hot(str(record.get("decision", "unknown")), DECISION_VOCAB))
    vector.extend(_one_hot(str(record.get("selected_source_module", "unknown")), SOURCE_MODULE_VOCAB))
    vector.extend(_one_hot(str(record.get("problem_layer", "unknown")), PROBLEM_LAYER_VOCAB))
    vector.extend(_one_hot(str(record.get("contract_stage", "unknown")), STAGE_VOCAB))
    vector.extend(_build_probe_context_vector(record))
    return vector


def build_backfill_feature_vector(record: dict[str, Any]) -> list[float]:
    """Convert one historical run backfill record into the same base numeric space."""
    vector: list[float] = [
        _float_feature(record.get("psnr"), scale=50.0),
        _float_feature(record.get("ssim")),
        _float_feature(record.get("lpips")),
        _float_feature(record.get("num_gs"), scale=1_000_000.0),
    ]
    vector.extend(_derive_backfill_runtime_bools(record))
    vector.extend(_one_hot("unknown", DECISION_VOCAB))
    vector.extend(_one_hot("unknown", SOURCE_MODULE_VOCAB))
    vector.extend(_one_hot(_map_issue_type_to_problem_layer(record.get("issue_type")), PROBLEM_LAYER_VOCAB))
    vector.extend(_one_hot(str(record.get("contract_stage", "unknown")), STAGE_VOCAB))
    vector.extend(_build_probe_context_vector(record))
    return vector


def build_augmented_feature_vector(record: dict[str, Any], teacher_labels: dict[str, Any] | None = None) -> list[float]:
    """Merge base feedback features with offline teacher semantic labels."""
    vector = build_feature_vector(record)
    vector.extend(build_teacher_feature_vector(teacher_labels))
    return vector


def build_backfill_augmented_feature_vector(record: dict[str, Any], teacher_labels: dict[str, Any] | None = None) -> list[float]:
    """Merge backfill run-level features with teacher semantic labels."""
    vector = build_backfill_feature_vector(record)
    vector.extend(build_teacher_feature_vector(teacher_labels or record.get("teacher_labels")))
    return vector


def extract_labeled_examples(records: Iterable[dict[str, Any]]) -> list[tuple[list[float], float, float]]:
    """Keep only labeled feedback rows and emit feature/label pairs."""
    examples: list[tuple[list[float], float, float]] = []
    for record in records:
        useful = record.get("decision_useful")
        if not isinstance(useful, bool):
            continue
        examples.append((build_feature_vector(record), 1.0 if useful else 0.0, 1.0))
    return examples


def extract_augmented_labeled_examples(records: Iterable[dict[str, Any]]) -> list[tuple[list[float], float, float]]:
    """Keep only labeled historical backfill rows and emit augmented feature/label pairs."""
    examples: list[tuple[list[float], float, float]] = []
    for record in records:
        useful = record.get("run_useful")
        if not isinstance(useful, bool):
            teacher = record.get("teacher_labels", {}) or {}
            useful = teacher.get("run_useful")
        if not isinstance(useful, bool):
            continue
        teacher_labels = record.get("teacher_labels")
        vector = build_backfill_augmented_feature_vector(record, teacher_labels)
        sample_weight = _sample_weight_from_teacher_labels(teacher_labels)
        examples.append((vector, 1.0 if useful else 0.0, sample_weight))
    return examples


@dataclass
class DecisionModelBatch:
    features: torch.Tensor
    labels: torch.Tensor
    sample_weights: torch.Tensor

    @property
    def feature_dim(self) -> int:
        return int(self.features.shape[1]) if self.features.ndim == 2 else 0

    @property
    def size(self) -> int:
        return int(self.labels.shape[0]) if self.labels.ndim == 1 else 0


def _build_batch(examples: list[tuple[list[float], float, float]], fallback_dim: int) -> DecisionModelBatch:
    if not examples:
        return DecisionModelBatch(
            features=torch.zeros((0, fallback_dim), dtype=torch.float32),
            labels=torch.zeros((0,), dtype=torch.float32),
            sample_weights=torch.zeros((0,), dtype=torch.float32),
        )
    features = torch.tensor([item[0] for item in examples], dtype=torch.float32)
    labels = torch.tensor([item[1] for item in examples], dtype=torch.float32)
    sample_weights = torch.tensor([item[2] for item in examples], dtype=torch.float32)
    return DecisionModelBatch(features=features, labels=labels, sample_weights=sample_weights)


def build_training_batch(records: Iterable[dict[str, Any]]) -> DecisionModelBatch:
    """Create one in-memory training batch from labeled outcome feedback."""
    return _build_batch(extract_labeled_examples(records), feature_vector_dim())


def build_augmented_training_batch(records: Iterable[dict[str, Any]]) -> DecisionModelBatch:
    """Create one in-memory training batch from labeled historical backfill rows."""
    return _build_batch(extract_augmented_labeled_examples(records), augmented_feature_vector_dim())


class DecisionOutcomeMLP(nn.Module):
    """Small structured-data classifier for decision usefulness."""

    def __init__(self, feature_dim: int | None = None, hidden_dim: int = 32):
        super().__init__()
        input_dim = feature_dim or feature_vector_dim()
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


def _train_model(
    batch: DecisionModelBatch,
    *,
    epochs: int,
    learning_rate: float,
    hidden_dim: int,
    seed: int,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    if batch.size == 0:
        raise ValueError("No labeled records were found.")

    model = DecisionOutcomeMLP(feature_dim=batch.feature_dim, hidden_dim=hidden_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    pos_count = int(batch.labels.sum().item())
    neg_count = int(batch.size - pos_count)
    if pos_count > 0 and neg_count > 0:
        pos_weight_value = float(neg_count / pos_count)
    else:
        pos_weight_value = 1.0
    pos_weight = torch.tensor([pos_weight_value], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss(reduction="none", pos_weight=pos_weight)

    losses: list[float] = []
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = model(batch.features)
        raw_loss = criterion(logits, batch.labels)
        loss = (raw_loss * batch.sample_weights).sum() / batch.sample_weights.sum().clamp_min(1e-6)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.item()))

    with torch.no_grad():
        probabilities = torch.sigmoid(model(batch.features))
        accuracy = ((probabilities >= 0.5).float() == batch.labels).float().mean().item()

    return {
        "model": model,
        "batch": batch,
        "losses": losses,
        "train_accuracy": float(accuracy),
        "feature_dim": batch.feature_dim,
        "dataset_size": batch.size,
        "positive_count": pos_count,
        "negative_count": neg_count,
        "pos_weight": pos_weight_value,
    }


def train_decision_model(
    records: Iterable[dict[str, Any]],
    *,
    epochs: int = 80,
    learning_rate: float = 1e-3,
    hidden_dim: int = 32,
    seed: int = 7,
) -> dict[str, Any]:
    """Train a minimal offline classifier from labeled feedback records."""
    batch = build_training_batch(records)
    return _train_model(batch, epochs=epochs, learning_rate=learning_rate, hidden_dim=hidden_dim, seed=seed)


def train_augmented_decision_model(
    records: Iterable[dict[str, Any]],
    *,
    epochs: int = 120,
    learning_rate: float = 1e-3,
    hidden_dim: int = 32,
    seed: int = 7,
) -> dict[str, Any]:
    """Train an offline classifier from historical backfill rows + teacher labels."""
    batch = build_augmented_training_batch(records)
    return _train_model(batch, epochs=epochs, learning_rate=learning_rate, hidden_dim=hidden_dim, seed=seed)


def predict_decision_usefulness(model: DecisionOutcomeMLP, record: dict[str, Any]) -> float:
    """Return a probability score in [0, 1] for one feedback-like record."""
    with torch.no_grad():
        features = torch.tensor([build_feature_vector(record)], dtype=torch.float32)
        probability = torch.sigmoid(model(features)).item()
    return float(probability)


def predict_augmented_decision_usefulness(
    model: DecisionOutcomeMLP,
    record: dict[str, Any],
    teacher_labels: dict[str, Any] | None = None,
) -> float:
    """Return a probability score in [0, 1] for one backfill-like record."""
    with torch.no_grad():
        features = torch.tensor([build_backfill_augmented_feature_vector(record, teacher_labels)], dtype=torch.float32)
        probability = torch.sigmoid(model(features)).item()
    return float(probability)


def load_feedback_records(audit_root: str | Path) -> list[dict[str, Any]]:
    """Load all outcome feedback records from one audit root."""
    history = OutcomeFeedbackHistory(audit_root)
    return history.load_records()


def load_jsonl_records(path: str | Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON records for offline learning."""
    file_path = Path(path)
    records: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records
