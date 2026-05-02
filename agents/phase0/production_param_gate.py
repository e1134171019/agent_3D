"""ProductionParamGate Agent - 為 SfM / 3DGS 生產層產出受控參數建議。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class ProductionParamGate:
    """根據目前驗證結果，輸出可被生產層腳本讀取的參數建議。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.pointcloud_report = None
        self.validation_report = None
        self.proposal = None
        self.decision = None
        self.sfm_plan = None
        self.train_plan = None

    @staticmethod
    def _read_json_if_exists(path: str):
        file_path = Path(path)
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def propose(self, pointcloud_report_path: str, validation_report_path: str) -> dict:
        self.pointcloud_report = self._read_json_if_exists(pointcloud_report_path)
        self.validation_report = self._read_json_if_exists(validation_report_path)

        self.sfm_plan = self._build_sfm_plan()
        self.train_plan = self._build_train_plan()

        self.proposal = {
            "proposal_id": "PPG-001",
            "timestamp": datetime.now().isoformat(),
            "proposal_text": "根據目前結果生成受控的 SfM / 3DGS 參數建議",
            "sfm_profile": self.sfm_plan.get("profile_name"),
            "train_profile": self.train_plan.get("profile_name"),
            "sfm_plan": self.sfm_plan,
            "train_plan": self.train_plan,
        }
        return self.proposal

    def _build_sfm_plan(self) -> dict[str, Any]:
        if not self.pointcloud_report:
            return {
                "profile_name": "hold_missing_upstream",
                "execution_policy": "manual_review",
                "recommended_params": {},
                "rationale": ["缺少上游 pointcloud report，暫不產生 SfM 參數"],
            }

        if self.pointcloud_report.get("can_proceed_to_3dgs", False):
            return {
                "profile_name": "hold_current_sfm",
                "execution_policy": "manual_review",
                "recommended_params": {},
                "rationale": ["目前 SfM gate 已通過，維持現行 SfM 參數"],
            }

        points3d_count = int(self.pointcloud_report.get("points3d_count", 0) or 0)
        cameras_count = int(self.pointcloud_report.get("cameras_count", 0) or 0)
        diagnosis = self.pointcloud_report.get("diagnosis", "SfM 品質不足")

        max_features = 12000
        seq_overlap = 12
        if points3d_count < 100000:
            max_features = 16000
        if cameras_count <= 1:
            seq_overlap = 15

        return {
            "profile_name": "sfm_recovery",
            "execution_policy": "orchestrated_rerun",
            "recommended_params": {
                "max_features": max_features,
                "seq_overlap": seq_overlap,
                "max_image_size": 1600,
                "use_gpu": True,
            },
            "rationale": [
                diagnosis,
                f"目前點雲數量 {points3d_count:,}",
                f"目前相機數量 {cameras_count}",
                "先提高特徵數與相鄰幀重疊，再觀察 SfM gate 是否改善",
            ],
        }

    def _build_train_plan(self) -> dict[str, Any]:
        if not self.pointcloud_report or not self.pointcloud_report.get("can_proceed_to_3dgs", False):
            return {
                "profile_name": "hold_until_sfm_pass",
                "execution_policy": "manual_review",
                "recommended_params": {},
                "rationale": ["SfM 尚未通過，暫不建議調整 3DGS 訓練參數"],
            }

        if not self.validation_report:
            return {
                "profile_name": "train_completion",
                "execution_policy": "orchestrated_rerun",
                "recommended_params": {
                    "iterations": 30000,
                    "densify_until": 15000,
                    "eval_steps": 1000,
                    "data_factor": 1,
                    "sh_degree": 3,
                },
                "rationale": ["尚未產生 validation_report，先完成一次完整 3DGS 基準訓練"],
            }

        if self.validation_report.get("overall_pass", False):
            return {
                "profile_name": "hold_current_train",
                "execution_policy": "manual_review",
                "recommended_params": {},
                "rationale": ["目前 3DGS 品質已通過，維持現行訓練參數"],
            }

        diagnosis = self.validation_report.get("diagnosis", {}) or {}
        recommended_action = diagnosis.get("recommended_action", "investigate")
        reason = diagnosis.get("reason", self.validation_report.get("decision_note", "3DGS 品質未通過"))
        psnr = self.validation_report.get("psnr", "N/A")
        ssim = self.validation_report.get("ssim", "N/A")
        lpips = self.validation_report.get("lpips", "N/A")

        if recommended_action == "retrain":
            profile_name = "quality_recovery"
            params = {
                "iterations": 40000,
                "densify_until": 20000,
                "eval_steps": 1000,
                "data_factor": 1,
                "sh_degree": 3,
            }
        else:
            profile_name = "investigate_then_retrain"
            params = {
                "iterations": 35000,
                "densify_until": 18000,
                "eval_steps": 1000,
                "data_factor": 1,
                "sh_degree": 3,
            }

        return {
            "profile_name": profile_name,
            "execution_policy": "orchestrated_rerun",
            "recommended_params": params,
            "rationale": [
                reason,
                f"當前指標：PSNR={psnr}, SSIM={ssim}, LPIPS={lpips}",
                "先在安全範圍內延長訓練與 densification，再重新評估",
            ],
        }

    def evaluate(self) -> dict:
        self.decision = {
            "evaluation_timestamp": datetime.now().isoformat(),
            "approved": True,
            "reason": "production_param_plans_generated",
            "sfm_profile": self.sfm_plan.get("profile_name") if self.sfm_plan else "unknown",
            "train_profile": self.train_plan.get("profile_name") if self.train_plan else "unknown",
        }
        return self.decision

    def execute(self, output_dir: str) -> dict:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        sfm_path = out_dir / "sfm_params.json"
        train_path = out_dir / "train_params.json"

        with open(sfm_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "status": "success",
                    **self.sfm_plan,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        with open(train_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "status": "success",
                    **self.train_plan,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        return {
            "status": "success",
            "sfm_params_path": str(sfm_path),
            "train_params_path": str(train_path),
            "sfm_profile": self.sfm_plan.get("profile_name"),
            "train_profile": self.train_plan.get("profile_name"),
        }
