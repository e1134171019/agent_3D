from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(r"D:\agent_test")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = Path(r"D:\agent_test\adapters\qwen_teacher.py")
spec = importlib.util.spec_from_file_location("qwen_teacher", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class QwenTeacherTests(unittest.TestCase):
    def test_parse_teacher_response_accepts_alias_keys(self):
        raw = """{
          \"has_historical_value\": true,
          \"role\": \"benchmark\",
          \"issue\": \"framework\",
          \"reason\": \"Unity 白霧仍在\",
          \"recommended_next_step\": \"保留 benchmark\",
          \"unity_status\": \"visual_fail\",
          \"confidence\": 0.8,
          \"why\": \"離線與 Unity 結果不一致\"
        }"""
        label = module.parse_teacher_response(raw)
        self.assertIs(label.run_useful, True)
        self.assertEqual(label.role, "benchmark")
        self.assertEqual(label.issue_type, "framework")
        self.assertEqual(label.failure_reason, "Unity 白霧仍在")
        self.assertEqual(label.next_recommendation, "保留 benchmark")
        self.assertEqual(label.unity_result, "visual_fail")
        self.assertEqual(label.confidence, 0.8)
        self.assertEqual(label.rationale, "離線與 Unity 結果不一致")

    def test_parse_teacher_response_extracts_json_from_preface(self):
        raw = """以下是結果：
        {
          \"run_useful\": false,
          \"role\": \"failed_probe\",
          \"issue_type\": \"framework\",
          \"failure_reason\": \"setup blocked\",
          \"next_recommendation\": \"inspect logs\",
          \"unity_result\": \"not_tested\",
          \"confidence\": 0.7,
          \"rationale\": \"sandbox did not finish\"
        }
        """
        label = module.parse_teacher_response(raw)
        self.assertIs(label.run_useful, False)
        self.assertEqual(label.role, "failed_probe")
        self.assertEqual(label.issue_type, "framework")

    def test_apply_summary_fallback_uses_historical_labels(self):
        label = module.QwenTeacherLabel(run_useful=None)
        summary = {
            "unity_result": "visual_fail",
            "historical_human_label": {
                "run_useful": True,
                "role": "benchmark",
                "issue_type": "framework",
                "failure_reason": "Unity 白霧仍在",
                "next_recommendation": "保留 benchmark",
            },
        }
        filled = module.apply_summary_fallback(label, summary)
        self.assertIs(filled.run_useful, True)
        self.assertEqual(filled.role, "benchmark")
        self.assertEqual(filled.issue_type, "framework")
        self.assertEqual(filled.unity_result, "visual_fail")
        self.assertEqual(filled.confidence, 0.55)

    def test_build_run_prompt_mentions_scaffold_probe_rules(self):
        prompt = module.build_run_prompt(
            {
                "run_id": "scaffold_gs_prepared_factorygaussian_u_base_750k_aa",
                "experiment_family": "scaffold_gs_probe",
                "contract_stage": "unknown",
                "train_mode": "scaffold_gs",
                "unity_result": "not_tested",
                "probe_context": {
                    "framework_name": "scaffold_gs",
                    "probe_status": "prepared",
                    "dataset_name": "factorygaussian",
                    "scene_name": "u_base_750k_aa",
                },
            }
        )
        self.assertIn("probe_context.framework_name=scaffold_gs", prompt)
        self.assertIn("probe_context.probe_status=prepared", prompt)
        self.assertIn('"framework_name": "scaffold_gs"', prompt)


if __name__ == "__main__":
    unittest.main()
