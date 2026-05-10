from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.historical_run_backfill import HistoricalRunBackfillRecord


DEFAULT_MANIFEST = Path(
    r"C:\3d-recon-pipeline\experimental\scaffold_gs_probe\data\factorygaussian\u_base_750k_aa\probe_manifest.json"
)
DEFAULT_OUTPUTS_ROOT = Path(r"C:\3d-recon-pipeline\experimental\scaffold_gs_probe\outputs")
DEFAULT_OUTPUT = Path(r"D:\agent_test\outputs\offline_learning\scaffold_probe_backfill_seed.jsonl")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _sanitize_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_") or "unknown"


def _scene_root(outputs_root: Path, manifest: dict[str, Any]) -> Path:
    dataset_name = str(manifest.get("dataset_name", "unknown"))
    scene_name = str(manifest.get("scene_name", "unknown"))
    return outputs_root / dataset_name / scene_name


def discover_model_roots(outputs_root: Path, manifest: dict[str, Any]) -> list[Path]:
    scene_root = _scene_root(outputs_root, manifest)
    if not scene_root.exists():
        return []

    roots: dict[str, Path] = {}
    for marker_name in ("cfg_args", "outputs.log"):
        for marker in scene_root.rglob(marker_name):
            if marker.is_file():
                roots[str(marker.parent)] = marker.parent
    return sorted(roots.values(), key=lambda item: item.stat().st_mtime)


def _latest_point_cloud_path(model_root: Path) -> Path | None:
    point_cloud_root = model_root / "point_cloud"
    if not point_cloud_root.exists():
        return None

    best_path: Path | None = None
    best_iteration = -1
    for candidate in point_cloud_root.glob("iteration_*/point_cloud.ply"):
        try:
            iteration = int(candidate.parent.name.split("_", 1)[1])
        except (IndexError, ValueError):
            iteration = -1
        if iteration > best_iteration:
            best_iteration = iteration
            best_path = candidate
    return best_path


def _read_ply_vertex_count(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None

    with path.open("rb") as fh:
        for raw_line in fh:
            line = raw_line.decode("ascii", errors="ignore").strip()
            if line.startswith("element vertex "):
                _, _, count_text = line.split()
                try:
                    return int(count_text)
                except ValueError:
                    return None
            if line == "end_header":
                break
    return None


def _load_results_metrics(model_root: Path) -> tuple[float | None, float | None, float | None]:
    results_path = model_root / "results.json"
    if not results_path.exists():
        return (None, None, None)

    payload = load_json(results_path)
    if not isinstance(payload, dict) or not payload:
        return (None, None, None)

    first_method = next(iter(payload.values()))
    if not isinstance(first_method, dict):
        return (None, None, None)

    return (
        _safe_float(first_method.get("PSNR")),
        _safe_float(first_method.get("SSIM")),
        _safe_float(first_method.get("LPIPS")),
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_id_from_model_root(model_root: Path) -> str:
    exp_name = _sanitize_token(model_root.parent.name)
    stamp = _sanitize_token(model_root.name)
    return f"scaffold_gs_{exp_name}_{stamp}"


def _base_probe_context(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "framework_name": "scaffold_gs",
        "manifest_path": str(manifest_path),
        "sandbox_root": str(manifest.get("sandbox_root", "")),
        "source_scene": str(manifest.get("source_scene", "")),
        "dataset_name": str(manifest.get("dataset_name", "unknown")),
        "scene_name": str(manifest.get("scene_name", "unknown")),
        "image_count": manifest.get("image_count"),
        "sparse_files": manifest.get("sparse_files", []),
    }


def build_prepared_record(manifest_path: Path, manifest: dict[str, Any]) -> HistoricalRunBackfillRecord:
    context = _base_probe_context(manifest_path, manifest)
    context["probe_status"] = "prepared"
    return HistoricalRunBackfillRecord(
        run_id=f"scaffold_gs_prepared_{_sanitize_token(context['dataset_name'])}_{_sanitize_token(context['scene_name'])}",
        experiment_family="scaffold_gs_probe",
        contract_stage="unknown",
        train_mode="scaffold_gs",
        unity_result="not_tested",
        run_useful=None,
        role="unknown",
        issue_type="unknown",
        failure_reason="Scaffold-GS sandbox scene is prepared, but no training artifact exists yet.",
        next_recommendation="Launch a short Scaffold-GS sandbox probe, then send the completed run through Qwen teacher review.",
        label_source="scaffold_probe_manifest",
        probe_context=context,
    )


def build_model_record(
    manifest_path: Path,
    manifest: dict[str, Any],
    model_root: Path,
) -> HistoricalRunBackfillRecord:
    context = _base_probe_context(manifest_path, manifest)
    point_cloud_path = _latest_point_cloud_path(model_root)
    results_path = model_root / "results.json"
    outputs_log_path = model_root / "outputs.log"
    cfg_args_path = model_root / "cfg_args"
    psnr, ssim, lpips = _load_results_metrics(model_root)
    num_gs = _read_ply_vertex_count(point_cloud_path)

    if point_cloud_path is not None or results_path.exists():
        probe_status = "trained"
        failure_reason = ""
        next_recommendation = "Send this Scaffold-GS run through Qwen teacher review, then compare it with the current gsplat Unity candidate."
        contract_stage = "train_complete"
    else:
        probe_status = "setup_blocked"
        failure_reason = "Scaffold-GS sandbox created a run directory, but no complete point_cloud/results artifact was found."
        next_recommendation = "Inspect outputs.log and dependency state before retrying the Scaffold-GS framework probe."
        contract_stage = "unknown"

    context.update(
        {
            "probe_status": probe_status,
            "model_root": str(model_root),
            "experiment_name": model_root.parent.name,
            "run_stamp": model_root.name,
            "cfg_args_path": str(cfg_args_path) if cfg_args_path.exists() else "",
            "outputs_log_path": str(outputs_log_path) if outputs_log_path.exists() else "",
            "results_path": str(results_path) if results_path.exists() else "",
            "point_cloud_path": str(point_cloud_path) if point_cloud_path and point_cloud_path.exists() else "",
        }
    )

    return HistoricalRunBackfillRecord(
        run_id=_run_id_from_model_root(model_root),
        experiment_family="scaffold_gs_probe",
        contract_stage=contract_stage,
        train_mode="scaffold_gs",
        psnr=psnr,
        ssim=ssim,
        lpips=lpips,
        num_gs=num_gs,
        unity_result="not_tested",
        run_useful=None,
        role="unknown",
        issue_type="unknown",
        failure_reason=failure_reason,
        next_recommendation=next_recommendation,
        label_source="scaffold_probe_manifest",
        probe_context=context,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline backfill seed rows from Scaffold-GS sandbox probe artifacts.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--outputs-root", type=Path, default=DEFAULT_OUTPUTS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    model_roots = discover_model_roots(args.outputs_root, manifest)

    if model_roots:
        records = [asdict(build_model_record(args.manifest, manifest, model_root)) for model_root in model_roots]
    else:
        records = [asdict(build_prepared_record(args.manifest, manifest))]

    write_jsonl(records, args.output)
    print(f"[OK] wrote {len(records)} scaffold probe seed record(s) -> {args.output}")


if __name__ == "__main__":
    main()
