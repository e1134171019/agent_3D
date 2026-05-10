from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

ROOT = Path(r"D:\agent_test")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE_PATH = Path(r"D:\agent_test\adapters\build_historical_run_backfill.py")
module = _load_module(MODULE_PATH, "build_historical_run_backfill")


class HistoricalRunBackfillTests(unittest.TestCase):
    def test_seed_records_have_expected_count_and_required_fields(self):
        records = module.build_seed_records()
        self.assertEqual(len(records), 20)
        for record in records:
            self.assertTrue(record["run_id"])
            self.assertIn(record["role"], {"benchmark", "unity_candidate", "failed_probe", "unknown"})
            self.assertIn(record["issue_type"], {"parameter", "framework", "export", "unity_render", "data", "mixed", "unknown"})
            self.assertIn(record["unity_result"], {"not_tested", "candidate", "visual_fail", "pass", "unknown"})

    def test_write_jsonl_roundtrip(self):
        records = module.build_seed_records()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "seed.jsonl"
            module.write_jsonl(records, out)
            lines = out.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 20)
            first = json.loads(lines[0])
            self.assertEqual(first["run_id"], "u_base_mcmc_fulltrain_20260418_155339")


if __name__ == "__main__":
    unittest.main()
