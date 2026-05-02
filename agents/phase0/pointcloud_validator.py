"""PointCloudValidator - Stage 0 Agent."""

from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from src.contract_io import read_json, write_json


class PointCloudValidator:
    """
    點雲品質驗證器。

    支援兩種輸入：
    1. 生產層已生成的上游報告（推薦）
    2. 較原始的點雲統計資料（向後相容）
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.min_cameras = 5
        self.min_points3d = 50000
        self.max_reprojection_error = 2.0

    @staticmethod
    def _load_json_robust(path: Path) -> Dict[str, Any]:
        return read_json(path, expect_object=True)

    def validate(self, stats_file: str | Path) -> Dict[str, Any]:
        stats_file = Path(stats_file)

        report = {
            "timestamp": datetime.now().isoformat(),
            "stats_file": str(stats_file.resolve()) if stats_file.exists() else str(stats_file),
            "can_proceed_to_3dgs": False,
            "diagnosis": "未檢查",
            "details": {},
        }

        if not stats_file.exists():
            report["diagnosis"] = f"統計文件不存在：{stats_file}"
            if self.verbose:
                print(f"FAIL {report['diagnosis']}")
            return report

        try:
            stats = self._load_json_robust(stats_file)
            if self.verbose:
                print(f"OK 讀取統計：{stats_file}")
        except Exception as e:
            report["diagnosis"] = f"無法解析 JSON：{str(e)}"
            if self.verbose:
                print(f"FAIL {report['diagnosis']}")
            return report

        # 模式 A: 直接消費生產層上游報告
        if "can_proceed_to_3dgs" in stats and "avg_reprojection_error" not in stats:
            report["cameras_count"] = stats.get("cameras_count")
            report["images_count"] = stats.get("images_count")
            report["registered_images_count"] = stats.get("registered_images_count")
            report["points3d_count"] = stats.get("points3d_count")
            report["details"] = {
                "source_mode": "upstream_report",
                "cameras_count": stats.get("cameras_count"),
                "images_count": stats.get("images_count"),
                "registered_images_count": stats.get("registered_images_count"),
                "points3d_count": stats.get("points3d_count"),
            }
            report["diagnosis"] = stats.get("diagnosis", "已讀取上游 SfM 驗證報告")
            report["can_proceed_to_3dgs"] = bool(stats.get("can_proceed_to_3dgs", False))
            if self.verbose:
                print(f"OK 使用上游報告結果：can_proceed_to_3dgs={report['can_proceed_to_3dgs']}")
            return report

        # 模式 B: 舊 raw stats 模式
        required_fields = ["cameras_count", "points3d_count", "avg_reprojection_error"]
        missing_fields = [field for field in required_fields if field not in stats]
        if missing_fields:
            report["diagnosis"] = f"統計數據缺失必要欄位：{missing_fields}"
            if self.verbose:
                print(f"FAIL {report['diagnosis']}")
            return report

        cameras_count = stats.get("cameras_count", 0)
        points3d_count = stats.get("points3d_count", 0)
        avg_repr_error = stats.get("avg_reprojection_error", 999)
        stats_diagnosis = stats.get("diagnosis", "")

        report["details"] = {
            "source_mode": "raw_stats",
            "cameras_count": cameras_count,
            "points3d_count": points3d_count,
            "avg_reprojection_error": avg_repr_error,
            "stats_diagnosis": stats_diagnosis,
        }
        report["cameras_count"] = cameras_count
        report["points3d_count"] = points3d_count
        report["avg_reprojection_error"] = avg_repr_error

        issues = []
        if cameras_count < self.min_cameras:
            issues.append(f"相機數量不足（{cameras_count} < {self.min_cameras}）")
        if points3d_count < self.min_points3d:
            issues.append(f"點雲過於稀疏（{points3d_count} < {self.min_points3d}）")
        if avg_repr_error > self.max_reprojection_error:
            issues.append(f"重投影誤差過高（{avg_repr_error:.2f} > {self.max_reprojection_error}）")

        if issues:
            report["diagnosis"] = "；".join(issues)
            report["can_proceed_to_3dgs"] = False
            if self.verbose:
                print(f"FAIL 驗證失敗：{report['diagnosis']}")
        else:
            report["diagnosis"] = "點雲品質可接受，可繼續進行 3DGS 訓練"
            report["can_proceed_to_3dgs"] = True
            if self.verbose:
                print(f"OK 驗證通過：{report['diagnosis']}")

        return report

    def validate_and_report(self, stats_file: str | Path, report_file: str | Path) -> bool:
        report = self.validate(stats_file)

        report_path = Path(report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            write_json(report_path, report)
            if self.verbose:
                print(f"OK 報告已保存：{report_path.resolve()}")
        except Exception as e:
            print(f"FAIL 無法寫出報告：{str(e)}")
            return report.get("can_proceed_to_3dgs", False)

        return report.get("can_proceed_to_3dgs", False)


def validate_pointcloud(
    stats_file: str | Path,
    report_file: str | Path,
    verbose: bool = True,
) -> bool:
    validator = PointCloudValidator(verbose=verbose)
    return validator.validate_and_report(stats_file, report_file)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python pointcloud_validator.py <stats_file> [report_file]")
        print()
        print("範例：")
        print("  python pointcloud_validator.py c:/3d-recon-pipeline/outputs/reports/pointcloud_validation_report.json")
        print()
        sys.exit(1)

    stats_path = sys.argv[1]
    report_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/phase0/pointcloud_validation_report.json"
    success = validate_pointcloud(stats_path, report_path, verbose=True)
    sys.exit(0 if success else 1)
