"""Historical run backfill schema for offline learning.

This module converts human-reviewed experiment history into a normalized
run-level record that can later be merged with teacher labels and outcome
feedback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HistoricalRunBackfillRecord:
    run_id: str
    experiment_family: str
    contract_stage: str
    train_mode: str = "unknown"
    cap_max: int | None = None
    antialiased: bool | None = None
    random_bkgd: bool | None = None
    mcmc_min_opacity: float | None = None
    mcmc_noise_lr: float | None = None
    psnr: float | None = None
    ssim: float | None = None
    lpips: float | None = None
    num_gs: int | None = None
    unity_result: str = "unknown"
    run_useful: bool | None = None
    role: str = "unknown"
    issue_type: str = "unknown"
    failure_reason: str = ""
    next_recommendation: str = ""
    label_source: str = "history_backfill"
    probe_context: dict[str, Any] = field(default_factory=dict)

    def to_teacher_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "run_id": payload["run_id"],
            "experiment_family": payload["experiment_family"],
            "contract_stage": payload["contract_stage"],
            "train_mode": payload["train_mode"],
            "params": {
                "cap_max": payload["cap_max"],
                "antialiased": payload["antialiased"],
                "random_bkgd": payload["random_bkgd"],
                "mcmc_min_opacity": payload["mcmc_min_opacity"],
                "mcmc_noise_lr": payload["mcmc_noise_lr"],
            },
            "metrics": {
                "psnr": payload["psnr"],
                "ssim": payload["ssim"],
                "lpips": payload["lpips"],
                "num_gs": payload["num_gs"],
            },
            "unity_result": payload["unity_result"],
            "known_labels": {
                "run_useful": payload["run_useful"],
                "role": payload["role"],
                "issue_type": payload["issue_type"],
                "failure_reason": payload["failure_reason"],
                "next_recommendation": payload["next_recommendation"],
            },
            "probe_context": payload["probe_context"],
        }


def backfill_record_schema() -> dict[str, str]:
    return {
        "run_id": "str",
        "experiment_family": "str",
        "contract_stage": "str",
        "train_mode": "str",
        "cap_max": "int | null",
        "antialiased": "bool | null",
        "random_bkgd": "bool | null",
        "mcmc_min_opacity": "float | null",
        "mcmc_noise_lr": "float | null",
        "psnr": "float | null",
        "ssim": "float | null",
        "lpips": "float | null",
        "num_gs": "int | null",
        "unity_result": "str",
        "run_useful": "bool | null",
        "role": "str",
        "issue_type": "str",
        "failure_reason": "str",
        "next_recommendation": "str",
        "label_source": "str",
        "probe_context": "dict",
    }
