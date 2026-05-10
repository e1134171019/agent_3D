from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.pytorch_decision_model import (
    load_jsonl_records,
    predict_augmented_decision_usefulness,
    train_augmented_decision_model,
)

DEFAULT_INPUT = Path(r"D:\agent_test\outputs\offline_learning\historical_run_backfill_teacher.jsonl")
DEFAULT_OUTPUT = Path(r"D:\agent_test\outputs\offline_learning\augmented_pytorch_baseline_report.json")


def run_leave_one_out(records: list[dict], *, epochs: int, learning_rate: float, hidden_dim: int, seed: int) -> dict[str, object]:
    if len(records) < 2:
        return {"loo_accuracy": None, "evaluated": 0, "predictions": []}

    predictions: list[dict[str, object]] = []
    correct = 0
    evaluated = 0

    for idx, held_out in enumerate(records):
        label = held_out.get("run_useful")
        if not isinstance(label, bool):
            teacher = held_out.get("teacher_labels", {}) or {}
            label = teacher.get("run_useful")
        if not isinstance(label, bool):
            continue

        train_records = [record for j, record in enumerate(records) if j != idx]
        train_result = train_augmented_decision_model(
            train_records,
            epochs=epochs,
            learning_rate=learning_rate,
            hidden_dim=hidden_dim,
            seed=seed,
        )
        probability = predict_augmented_decision_usefulness(
            train_result["model"],
            held_out,
            held_out.get("teacher_labels"),
        )
        pred = probability >= 0.5
        if pred == label:
            correct += 1
        evaluated += 1
        predictions.append({
            "run_id": held_out.get("run_id"),
            "label": label,
            "probability": round(probability, 6),
            "prediction": pred,
        })

    accuracy = (correct / evaluated) if evaluated else None
    return {
        "loo_accuracy": accuracy,
        "evaluated": evaluated,
        "predictions": predictions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train offline PyTorch baseline on historical backfill + teacher labels.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=180)
    parser.add_argument("--lr", type=float, default=0.004)
    parser.add_argument("--hidden-dim", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    records = load_jsonl_records(args.input)
    result = train_augmented_decision_model(
        records,
        epochs=args.epochs,
        learning_rate=args.lr,
        hidden_dim=args.hidden_dim,
        seed=args.seed,
    )
    loo = run_leave_one_out(
        records,
        epochs=args.epochs,
        learning_rate=args.lr,
        hidden_dim=args.hidden_dim,
        seed=args.seed,
    )
    report = {
        "input_path": str(args.input),
        "dataset_size": result["dataset_size"],
        "feature_dim": result["feature_dim"],
        "train_accuracy": result["train_accuracy"],
        "positive_count": result["positive_count"],
        "negative_count": result["negative_count"],
        "pos_weight": result["pos_weight"],
        "leave_one_out_accuracy": loo["loo_accuracy"],
        "leave_one_out_evaluated": loo["evaluated"],
        "leave_one_out_predictions": loo["predictions"],
        "loss_first": result["losses"][0],
        "loss_last": result["losses"][-1],
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "hidden_dim": args.hidden_dim,
        "seed": args.seed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[OK] wrote report -> {args.output}")


if __name__ == "__main__":
    main()
