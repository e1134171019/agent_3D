"""Offline PyTorch decision model built from outcome feedback artifacts.

This module is intentionally kept outside the formal 6-core runtime.
It is a learning adapter for experimentation, not the formal arbiter.
"""

from __future__ import annotations

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
    return vector


def extract_labeled_examples(records: Iterable[dict[str, Any]]) -> list[tuple[list[float], float]]:
    """Keep only labeled feedback rows and emit feature/label pairs."""
    examples: list[tuple[list[float], float]] = []
    for record in records:
        useful = record.get("decision_useful")
        if not isinstance(useful, bool):
            continue
        examples.append((build_feature_vector(record), 1.0 if useful else 0.0))
    return examples


@dataclass
class DecisionModelBatch:
    features: torch.Tensor
    labels: torch.Tensor

    @property
    def feature_dim(self) -> int:
        return int(self.features.shape[1]) if self.features.ndim == 2 else 0

    @property
    def size(self) -> int:
        return int(self.labels.shape[0]) if self.labels.ndim == 1 else 0


def build_training_batch(records: Iterable[dict[str, Any]]) -> DecisionModelBatch:
    """Create one in-memory training batch from labeled outcome feedback."""
    examples = extract_labeled_examples(records)
    if not examples:
        return DecisionModelBatch(
            features=torch.zeros((0, feature_vector_dim()), dtype=torch.float32),
            labels=torch.zeros((0,), dtype=torch.float32),
        )

    features = torch.tensor([item[0] for item in examples], dtype=torch.float32)
    labels = torch.tensor([item[1] for item in examples], dtype=torch.float32)
    return DecisionModelBatch(features=features, labels=labels)


def feature_vector_dim() -> int:
    return 10 + len(DECISION_VOCAB) + len(SOURCE_MODULE_VOCAB) + len(PROBLEM_LAYER_VOCAB) + len(STAGE_VOCAB)


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


def train_decision_model(
    records: Iterable[dict[str, Any]],
    *,
    epochs: int = 80,
    learning_rate: float = 1e-3,
    hidden_dim: int = 32,
    seed: int = 7,
) -> dict[str, Any]:
    """Train a minimal offline classifier from labeled feedback records."""
    torch.manual_seed(seed)
    batch = build_training_batch(records)
    if batch.size == 0:
        raise ValueError("No labeled outcome feedback records were found.")

    model = DecisionOutcomeMLP(feature_dim=batch.feature_dim, hidden_dim=hidden_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    criterion = nn.BCEWithLogitsLoss()

    losses: list[float] = []
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = model(batch.features)
        loss = criterion(logits, batch.labels)
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
    }


def predict_decision_usefulness(model: DecisionOutcomeMLP, record: dict[str, Any]) -> float:
    """Return a probability score in [0, 1] for one feedback-like record."""
    with torch.no_grad():
        features = torch.tensor([build_feature_vector(record)], dtype=torch.float32)
        probability = torch.sigmoid(model(features)).item()
    return float(probability)


def load_feedback_records(audit_root: str | Path) -> list[dict[str, Any]]:
    """Load all outcome feedback records from one audit root."""
    history = OutcomeFeedbackHistory(audit_root)
    return history.load_records()
