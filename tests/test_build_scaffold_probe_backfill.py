from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(r"D:\agent_test")
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

MODULE_PATH = Path(r"D:\agent_test\adapters\build_scaffold_probe_backfill.py")
spec = importlib.util.spec_from_file_location("build_scaffold_probe_backfill", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class BuildScaffoldProbeBackfillTests(unittest.TestCase):
    def test_build_prepared_record_when_outputs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_json(
                root / "probe_manifest.json",
                {
                    "sandbox_root": r"C:\3d-recon-pipeline\experimental\scaffold_gs_probe",
                    "source_scene": r"C:\3d-recon-pipeline\outputs\experiments\train_probes\demo\_colmap_scene",
                    "dataset_name": "factorygaussian",
                    "scene_name": "u_base_750k_aa",
                    "image_count": 853,
                    "sparse_files": ["cameras.bin", "points3D.bin"],
                },
            )
            manifest = module.load_json(manifest_path)
            record = module.build_prepared_record(manifest_path, manifest)

            self.assertEqual(record.train_mode, "scaffold_gs")
            self.assertEqual(record.contract_stage, "unknown")
            self.assertIsNone(record.run_useful)
            self.assertEqual(record.probe_context["probe_status"], "prepared")

    def test_build_model_record_reads_metrics_and_point_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_json(
                root / "probe_manifest.json",
                {
                    "sandbox_root": r"C:\3d-recon-pipeline\experimental\scaffold_gs_probe",
                    "source_scene": r"C:\3d-recon-pipeline\outputs\experiments\train_probes\demo\_colmap_scene",
                    "dataset_name": "factorygaussian",
                    "scene_name": "u_base_750k_aa",
                    "image_count": 853,
                    "sparse_files": ["cameras.bin", "points3D.bin"],
                },
            )
            model_root = root / "outputs" / "factorygaussian" / "u_base_750k_aa" / "baseline" / "20260507_010000"
            write_text(model_root / "cfg_args", "--demo")
            write_json(
                model_root / "results.json",
                {
                    "ours_30000": {
                        "SSIM": 0.9123,
                        "PSNR": 27.4567,
                        "LPIPS": 0.1512,
                    }
                },
            )
            write_text(
                model_root / "point_cloud" / "iteration_30000" / "point_cloud.ply",
                "ply\nformat binary_little_endian 1.0\nelement vertex 12345\nend_header\n",
            )

            manifest = module.load_json(manifest_path)
            record = module.build_model_record(manifest_path, manifest, model_root)

            self.assertEqual(record.contract_stage, "train_complete")
            self.assertEqual(record.psnr, 27.4567)
            self.assertEqual(record.ssim, 0.9123)
            self.assertEqual(record.lpips, 0.1512)
            self.assertEqual(record.num_gs, 12345)
            self.assertEqual(record.probe_context["probe_status"], "trained")
            self.assertTrue(record.probe_context["results_path"].endswith("results.json"))


if __name__ == "__main__":
    unittest.main()
