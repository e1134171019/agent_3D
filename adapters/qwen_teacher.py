"""Local Ollama/Qwen teacher adapter for offline semantic labeling.

This adapter is outside the formal 6-core runtime. It is used to backfill
historical experiment runs with semantic labels that a tabular or PyTorch model
can later consume.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any
from urllib import request

ROLE_VOCAB = ("benchmark", "unity_candidate", "failed_probe", "unknown")
ISSUE_TYPE_VOCAB = ("parameter", "framework", "export", "unity_render", "data", "mixed", "unknown")
UNITY_RESULT_VOCAB = ("not_tested", "candidate", "visual_fail", "pass", "unknown")


@dataclass
class QwenTeacherLabel:
    run_useful: bool | None
    role: str = "unknown"
    issue_type: str = "unknown"
    failure_reason: str = ""
    next_recommendation: str = ""
    unity_result: str = "unknown"
    confidence: float = 0.0
    rationale: str = ""

    def normalized(self) -> "QwenTeacherLabel":
        return QwenTeacherLabel(
            run_useful=self.run_useful if isinstance(self.run_useful, bool) else None,
            role=self.role if self.role in ROLE_VOCAB else "unknown",
            issue_type=self.issue_type if self.issue_type in ISSUE_TYPE_VOCAB else "unknown",
            failure_reason=str(self.failure_reason or ""),
            next_recommendation=str(self.next_recommendation or ""),
            unity_result=self.unity_result if self.unity_result in UNITY_RESULT_VOCAB else "unknown",
            confidence=_clamp_confidence(self.confidence),
            rationale=str(self.rationale or ""),
        )

    def to_feature_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return asdict(normalized)


def _clamp_confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def teacher_output_schema() -> dict[str, Any]:
    return {
        "run_useful": "bool | null",
        "role": list(ROLE_VOCAB),
        "issue_type": list(ISSUE_TYPE_VOCAB),
        "failure_reason": "str",
        "next_recommendation": "str",
        "unity_result": list(UNITY_RESULT_VOCAB),
        "confidence": "0.0 ~ 1.0",
        "rationale": "str",
    }


def build_run_prompt(run_summary: dict[str, Any]) -> str:
    return (
        "你是 3DGS / Unity 實驗審查 teacher。\n"
        "任務：把單次 run 摘要轉成固定 schema JSON。\n"
        "只輸出單一 JSON object，不要輸出 markdown，不要輸出說明文字。\n"
        "所有欄位都必填，不可省略。\n"
        f"role 只能是: {ROLE_VOCAB}\n"
        f"issue_type 只能是: {ISSUE_TYPE_VOCAB}\n"
        f"unity_result 只能是: {UNITY_RESULT_VOCAB}\n"
        "run_useful 可以是 true、false 或 null。\n"
        "confidence 必須是 0.55 到 0.95 的小數，不可輸出 0。\n"
        "若資訊不足，可以使用 unknown，但要在 rationale 解釋為何不足。\n"
        "判斷規則：\n"
        "1. 離線最佳但 Unity 視覺失敗，通常是 role=benchmark、issue_type=framework、unity_result=visual_fail。\n"
        "2. 可作目前 Unity 候選但未達可交付，通常是 role=unity_candidate、unity_result=candidate。\n"
        "3. 單變數 probe 沒有升 full train 或正式被否決，通常是 role=failed_probe。\n"
        "4. export-side probe 無效時，issue_type 應優先判為 export 或 unity_render，不要留 unknown。\n"
        "5. 上游路線顯著差於 U_base + MCMC，issue_type 可判為 data 或 parameter，但不要留 unknown。\n"
        "6. 若 probe_context.framework_name=scaffold_gs，代表這是新框架 sandbox probe，不要把它當正式主線 benchmark。\n"
        "7. 若 probe_context.probe_status=prepared，代表只有 sandbox 與資料已就緒、尚未完成訓練；此時 run_useful 應為 null，role 應為 unknown，unity_result 通常為 not_tested。\n"
        "8. 若 probe_context.probe_status=setup_blocked，代表環境或編譯阻塞；role 通常是 failed_probe，issue_type 優先 framework，不要誤判成 parameter。\n"
        "9. 若 scaffold_gs 已產出 point_cloud 或 results.json，但 Unity 尚未驗證，優先視為 framework probe；只有在摘要明確指出可回到 Unity chain 時才考慮 unity_candidate。\n"
        "輸出格式必須精確符合：\n"
        "{\n"
        '  "run_useful": null,\n'
        '  "role": "unknown",\n'
        '  "issue_type": "unknown",\n'
        '  "failure_reason": "...",\n'
        '  "next_recommendation": "...",\n'
        '  "unity_result": "not_tested",\n'
        '  "confidence": 0.55,\n'
        '  "rationale": "..."\n'
        "}\n"
        "輸入 run 摘要如下：\n"
        f"{json.dumps(run_summary, ensure_ascii=False, indent=2)}\n"
    )



KEY_ALIASES = {
    "has_historical_value": "run_useful",
    "historical_value": "run_useful",
    "useful": "run_useful",
    "recommended_next_step": "next_recommendation",
    "next_step": "next_recommendation",
    "issue": "issue_type",
    "reason": "failure_reason",
    "unity_status": "unity_result",
    "visual_result": "unity_result",
    "why": "rationale",
}


def parse_teacher_response(raw_text: str) -> QwenTeacherLabel:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()
    elif not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("teacher response must be a JSON object")

    normalized_payload = {}
    valid_fields = {field.name for field in fields(QwenTeacherLabel)}
    for key, value in payload.items():
        target_key = KEY_ALIASES.get(key, key)
        if target_key in valid_fields:
            normalized_payload[target_key] = value

    return QwenTeacherLabel(**normalized_payload).normalized()


def apply_summary_fallback(label: QwenTeacherLabel, run_summary: dict[str, Any]) -> QwenTeacherLabel:
    hist = run_summary.get("historical_human_label", {}) or {}
    fallback_used = False

    run_useful = label.run_useful
    if run_useful is None and isinstance(hist.get("run_useful"), bool):
        run_useful = hist.get("run_useful")
        fallback_used = True

    role = label.role
    if role == "unknown":
        hist_role = hist.get("role")
        if hist_role in ROLE_VOCAB:
            role = hist_role
            fallback_used = True

    issue_type = label.issue_type
    if issue_type == "unknown":
        hist_issue = hist.get("issue_type")
        if hist_issue in ISSUE_TYPE_VOCAB:
            issue_type = hist_issue
            fallback_used = True

    unity_result = label.unity_result
    if unity_result == "unknown":
        source_unity = run_summary.get("unity_result")
        if source_unity in UNITY_RESULT_VOCAB:
            unity_result = source_unity
            fallback_used = True

    failure_reason = label.failure_reason or str(hist.get("failure_reason") or "")
    if not label.failure_reason and failure_reason:
        fallback_used = True

    next_recommendation = label.next_recommendation or str(hist.get("next_recommendation") or "")
    if not label.next_recommendation and next_recommendation:
        fallback_used = True

    rationale = label.rationale or failure_reason
    confidence = label.confidence
    if confidence == 0.0 and fallback_used:
        confidence = 0.55

    return QwenTeacherLabel(
        run_useful=run_useful,
        role=role,
        issue_type=issue_type,
        failure_reason=failure_reason,
        next_recommendation=next_recommendation,
        unity_result=unity_result,
        confidence=confidence,
        rationale=rationale,
    ).normalized()


class LocalOllamaTeacher:
    def __init__(self, *, model: str = "qwen2.5:14b", base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def classify_run(self, run_summary: dict[str, Any]) -> QwenTeacherLabel:
        payload = {
            "model": self.model,
            "prompt": build_run_prompt(run_summary),
            "stream": False,
            "format": "json",
        }
        req = request.Request(
            url=f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=120) as resp:
            response_payload = json.loads(resp.read().decode("utf-8"))
        parsed = parse_teacher_response(response_payload.get("response", "{}"))
        return apply_summary_fallback(parsed, run_summary)
