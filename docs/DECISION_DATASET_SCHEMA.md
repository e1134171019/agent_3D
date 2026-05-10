# Decision Dataset Schema

這份文件只定義離線學習層使用的資料格式，不變更正式 6-core runtime 規則。

## 原則
- 正式 runtime 仍以 `state / event / candidate / arbiter_decision / outcome_feedback` 為唯一決策主線。
- `PyTorch` 與未來 `TabPFN` 只讀離線資料，不直接改寫 `latest_*_decision.json`。
- 真正的離線學習入口是 `adapters/train_teacher_augmented_baseline.py` 或後續 trainer；`tests/test_pytorch_decision_model.py` 只驗證 deterministic schema / feature merge / baseline 介面。
- 本機 `Ollama / Qwen` 只扮演 teacher / labeler / explainer，不直接進入正式 arbiter。

## 1. Historical Run Backfill Schema

歷史實驗回填的最小欄位如下：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `run_id` | `str` | 唯一 run 識別 |
| `experiment_family` | `str` | 例如 `mcmc_probe` / `unity_export_probe` |
| `contract_stage` | `str` | `sfm_complete` / `train_complete` / `export_complete` |
| `train_mode` | `str` | `mcmc` / `default` / `unknown` |
| `cap_max` | `int?` | 例如 `750000` / `1000000` |
| `antialiased` | `bool?` | 是否開啟 antialiased |
| `random_bkgd` | `bool?` | 是否開啟 random background |
| `mcmc_min_opacity` | `float?` | MCMC 最低透明度 |
| `mcmc_noise_lr` | `float?` | MCMC noise lr |
| `psnr` | `float?` | 觀測 PSNR |
| `ssim` | `float?` | 觀測 SSIM |
| `lpips` | `float?` | 觀測 LPIPS |
| `num_gs` | `int?` | 最終高斯數 |
| `unity_result` | `str` | `not_tested` / `candidate` / `visual_fail` / `pass` |
| `run_useful` | `bool?` | 這個 run 本身是否有歷史價值 |
| `role` | `str` | `benchmark` / `unity_candidate` / `failed_probe` / `unknown` |
| `issue_type` | `str` | `parameter` / `framework` / `export` / `unity_render` / `data` / `mixed` / `unknown` |
| `failure_reason` | `str` | 短文字理由 |
| `next_recommendation` | `str` | 下一步建議 |
| `label_source` | `str` | `history_backfill` / `qwen_teacher` / `human_review` |
| `probe_context` | `dict` | 可選的 framework-specific sandbox 上下文；目前用於 `Scaffold-GS` probe |

## 2. Qwen Teacher Output Schema

本機 `Ollama / Qwen` 只輸出結構化 JSON，不直接產生正式 decision。

```json
{
  "run_useful": true,
  "role": "benchmark",
  "issue_type": "framework",
  "failure_reason": "Unity 白霧與 halo 顯示目前是框架表達限制，不是單純參數問題",
  "next_recommendation": "轉入 reflection-aware 3DGS framework evaluation",
  "unity_result": "visual_fail",
  "confidence": 0.82,
  "rationale": "離線 LPIPS 很強，但 Unity 視覺失敗，符合 benchmark 而非 deployment winner"
}
```

### 欄位約束
- `role` 只允許：`benchmark`、`unity_candidate`、`failed_probe`、`unknown`
- `issue_type` 只允許：`parameter`、`framework`、`export`、`unity_render`、`data`、`mixed`、`unknown`
- `unity_result` 只允許：`not_tested`、`candidate`、`visual_fail`、`pass`、`unknown`
- `confidence` 為 `0.0 ~ 1.0`
- `confidence` 的正式用途是 **offline learner sample weight**，不是 formal runtime 欄位，也不是主要 feature 語意欄位
- `run_useful` 是 run-level supervision，不得直接放進 offline learner 的 teacher feature vector，以避免 target leakage
- `probe_context` 目前允許攜帶：
  - `framework_name`
  - `probe_status`
  - `dataset_name`
  - `scene_name`
  - `source_scene`
  - `model_root`
  - `results_path`
  - `point_cloud_path`
  - 其他 sandbox-only 輔助欄位

## 3. 模型層分工
- `Qwen teacher`：補語意欄位與弱標註
- `PyTorch baseline`：學結構化特徵 + teacher 語意欄位
- `TabPFN`：保留為未來 tabular backend 候選，不在目前正式測試內直接依賴

### 補充規則

- `issue_type` 與 formal runtime 的 `problem_layer` 不是同一個 vocab。
- 歷史 backfill 進 base vector 時，必須先做顯式投影：
  - `parameter -> parameter`
  - `data -> data`
  - `framework -> framework`
  - `export -> framework`
  - `unity_render -> framework`
  - `mixed -> unknown`
  - `unknown -> unknown`
- `confidence` 不直接作為 teacher feature 主欄位；目前正式做法是把它轉成 offline 訓練 sample weight。
- backfill base vector 內的 runtime-style bool 不再全部硬填 `0.0`；目前採保守推導：
  - `can_proceed <- unity_result in {candidate, pass}`
  - `requires_human_review <- benchmark or visual_fail/unknown`
  - `wasted_run <- run_useful=false and role=failed_probe`
  - `repeated_problem <- issue_type in {parameter, mixed} and unity_result in {visual_fail, not_tested, unknown}`
- `probe_context.framework_name` 與 `probe_context.probe_status` 目前會進 offline feature vector，讓 learner 能辨識 `gsplat` 與 `Scaffold-GS` 的 probe 來源與狀態。

## 4. 測試約束
- `tests/test_pytorch_decision_model.py` 保持 deterministic。
- 不直接呼叫本機 Ollama。
- 對 `Qwen teacher` 一律使用 mocked / synthetic JSON 輸出驗證 schema 與 feature merge。


