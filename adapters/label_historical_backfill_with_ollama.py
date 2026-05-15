from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.qwen_teacher import LocalOllamaTeacher


DEFAULT_INPUT = Path(r"D:\agent_test\outputs\offline_learning\historical_run_backfill_seed.jsonl")
DEFAULT_OUTPUT = Path(r"D:\agent_test\outputs\offline_learning\historical_run_backfill_teacher.jsonl")


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def merge_teacher_output(record: dict, teacher_json: dict) -> dict:
    merged = dict(record)
    merged["teacher_labels"] = teacher_json
    merged["label_source"] = "qwen_teacher"
    return merged


def merge_teacher_error(record: dict, error: Exception) -> dict:
    merged = dict(record)
    merged["teacher_labels"] = {
        "run_useful": None,
        "role": "unknown",
        "issue_type": "unknown",
        "failure_reason": str(record.get("failure_reason") or ""),
        "next_recommendation": str(record.get("next_recommendation") or ""),
        "unity_result": str(record.get("unity_result") or "unknown"),
        "confidence": 0.0,
        "rationale": f"teacher labeling failed: {error}",
    }
    merged["label_source"] = "qwen_teacher_error"
    merged["teacher_error"] = str(error)
    return merged


def build_teacher_summary(record: dict) -> dict:
    return {
        "run_id": record.get("run_id"),
        "experiment_family": record.get("experiment_family"),
        "contract_stage": record.get("contract_stage"),
        "train_mode": record.get("train_mode"),
        "cap_max": record.get("cap_max"),
        "antialiased": record.get("antialiased"),
        "random_bkgd": record.get("random_bkgd"),
        "mcmc_min_opacity": record.get("mcmc_min_opacity"),
        "mcmc_noise_lr": record.get("mcmc_noise_lr"),
        "psnr": record.get("psnr"),
        "ssim": record.get("ssim"),
        "lpips": record.get("lpips"),
        "num_gs": record.get("num_gs"),
        "unity_result": record.get("unity_result"),
        "probe_context": record.get("probe_context", {}) or {},
        "historical_human_label": {
            "run_useful": record.get("run_useful"),
            "role": record.get("role"),
            "issue_type": record.get("issue_type"),
            "failure_reason": record.get("failure_reason"),
            "next_recommendation": record.get("next_recommendation"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Label backfill records with local Ollama teacher JSON.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="qwen2.5:14b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--no-resume", action="store_true", help="Do not reuse labels already present in the output file.")
    parser.add_argument("--refresh-null-scaffold", action="store_true", help="Relabel scaffold rows (trained/reviewed/setup_blocked) so teacher semantics stay consistent after policy changes.")
    args = parser.parse_args()

    teacher = LocalOllamaTeacher(model=args.model, base_url=args.base_url)
    records = load_jsonl(args.input)
    existing_by_run_id = {}
    if args.output.exists() and not args.no_resume:
        existing_by_run_id = {str(item.get("run_id")): item for item in load_jsonl(args.output)}

    labeled: list[dict] = []
    for index, record in enumerate(records, start=1):
        run_id = str(record.get("run_id"))
        if run_id in existing_by_run_id:
            existing = existing_by_run_id[run_id]
            teacher_labels = existing.get("teacher_labels", {}) or {}
            probe_context = record.get("probe_context", {}) or {}
            should_refresh_null_scaffold = (
                args.refresh_null_scaffold
                and str(probe_context.get("framework_name", "")).lower() == "scaffold_gs"
                and str(probe_context.get("probe_status", "unknown")) in {"trained", "reviewed", "setup_blocked"}
            )
            if not should_refresh_null_scaffold:
                labeled.append(existing)
                print(f"[SKIP] reused {index}/{len(records)} :: {record.get('run_id')}")
                continue
            print(f"[REFRESH] relabel {index}/{len(records)} :: {record.get('run_id')}")
        summary = build_teacher_summary(record)
        try:
            teacher_label = teacher.classify_run(summary)
            labeled.append(merge_teacher_output(record, teacher_label.to_feature_dict()))
            print(f"[OK] labeled {index}/{len(records)} :: {record.get('run_id')}")
        except Exception as exc:
            labeled.append(merge_teacher_error(record, exc))
            print(f"[WARN] teacher failed {index}/{len(records)} :: {record.get('run_id')} :: {exc}")

    write_jsonl(labeled, args.output)
    print(f"[OK] wrote teacher labels -> {args.output}")


if __name__ == "__main__":
    main()
