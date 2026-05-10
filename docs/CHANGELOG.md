# Agent System V1 — CHANGELOG

> 角色：本檔案紀錄 6-core 結構升級後的所有 dated changes（從 2026-04-30 開始）。
> 規則：新增 dated entry 時，**只**改本檔案，不再內聯到 [`AGENT_SYSTEM_V1.md`](AGENT_SYSTEM_V1.md) / [`/.instructions.md`](../.instructions.md) / [`README.md`](README.md)。
> 順序：reverse chronological（新 → 舊）。

---

## 2026-05-10 — Runtime Consistency 修正

- `AdaptiveThreshold.get_trend()` 的 LPIPS 方向已固定：LPIPS 下降才是 `improving`，上升是 `declining`；不得再用與 PSNR/SSIM 相同方向判讀。
- `AdaptiveThreshold.get_threshold()` 的通用上下界改為依 metric 收斂；正式 gate 仍以 `MapValidator.evaluate()` 傳入的 min/max 為最終保護。
- `MapDiagnostics` 必須吃與 `ValidationMetrics` 對齊的 threshold，不得另行硬編碼一份品質門檻。
- `MapValidator._analyze_history()` 必須同時計算 PSNR/SSIM/LPIPS trend；不得讓 `ssim_trend` / `lpips_trend` 永久固定為 `unknown`。
- `MapValidator` / `ProductionParamGate` 讀正式 JSON 時必須走 `src.contract_io.read_json`，不得手寫 raw `open()+json.load()` 當主要入口。
- `ProductionParamGate.evaluate()` 保留既有 `approved/overall_pass` 相容語義，但新增 `rerun_actionable / sfm_stage_passed / train_stage_passed`，避免把「有 rerun plan」誤解成「stage 健康」。
- `Ollama/Qwen` teacher 標註必須可續跑；單筆 teacher 失敗只能標記該筆 `qwen_teacher_error`，不得中斷整批資料回填。
- `CoverageStrategy._normalize_path()` 不得使用 `lstrip("./")` 處理路徑；絕對路徑必須正規化回正式 `src/...` 模組名後再比對。

---

## 2026-05-09 — Offline Learning 分層規則

- `adapters/pytorch_decision_model.py`：歷史 backfill 會先把 `issue_type` 顯式投影回 formal `problem_layer` 空間；teacher `confidence` 現在主要作為 offline training 的 sample weight，而不是主要輸入特徵。
- `adapters/pytorch_decision_model.py`：teacher `run_useful` 不得直接進 teacher feature vector；run-level supervision 與 feature space 要分離，避免 offline learner 偷讀 target。
- `adapters/pytorch_decision_model.py`：historical backfill 的 6 個 runtime-style bool 會做保守推導，不再全部硬填 `0.0`。
- `probe_context`：historical backfill 現在允許攜帶 framework-specific sandbox 上下文；目前第一個用途是 `Scaffold-GS`。
- `adapters/build_scaffold_probe_backfill.py`：把 `C:\3d-recon-pipeline\experimental\scaffold_gs_probe` 的 manifest / outputs 轉成離線 seed records。
- `adapters/label_historical_backfill_with_ollama.py`：現在會把 `probe_context` 一起送進本機 `Ollama/Qwen`，讓 teacher 能辨識 `prepared` / `trained` / `setup_blocked` 的框架 probe 狀態。

---

## 2026-05-06 — Offline Teacher / Dataset Layer

### 規則
- 正式 6-core runtime 不變。
- 本機 Ollama / Qwen 只作 teacher / labeler / explainer，不直接參與正式 arbiter runtime。
- 歷史 run 回填與 teacher 輸出格式，統一以 [`DECISION_DATASET_SCHEMA.md`](DECISION_DATASET_SCHEMA.md) 為準。
- `tests/test_pytorch_decision_model.py` 僅允許 deterministic mocked teacher 輸出；不得在測試內直接呼叫 Ollama 或要求下載 Qwen / TabPFN 套件。
- 真正的離線學習入口是 `adapters/train_teacher_augmented_baseline.py` 或後續 trainer，不是 `tests/test_pytorch_decision_model.py`。
- offline learner 讀到 `issue_type` 時，必須先顯式投影回 formal `problem_layer` 空間；teacher `confidence` 只作 sample weight，不得偷渡成 formal runtime 決策欄位。
- offline learner 不允許把 teacher `run_useful` 直接當輸入特徵；該欄位只屬於 run-level supervision，不屬於 feature space。
- historical backfill 轉 base vector 時，runtime-style bool 必須做保守推導，避免整排固定 `0.0` 造成資訊真空。
- 對話框 AI 角色是 meta evaluator / reviewer：審查 teacher prompt、schema、feature 與模型報告，不直接取代 formal runtime。

### 落地的 adapters
- `adapters/build_historical_run_backfill.py`：建立第一批 `historical_run_backfill_seed.jsonl`，只回填已完成且已有正式結論的 run。
- `adapters/label_historical_backfill_with_ollama.py`：使用本機 `Ollama/Qwen` 為 seed records 產生 teacher JSON，不進 formal runtime。
- `adapters/train_teacher_augmented_baseline.py`：正式 offline trainer，負責吸收 backfill + teacher labels；不得直接改寫 `latest_*_decision.json`。
- `outputs/offline_learning/`：離線學習資料層，與 `outputs/phase0` 正式 feedback 分離。

---

## 2026-05-01 — 第二輪 stage ablation

- 驗證報告：`C:\tmp\agent_stage_ablation\stage_ablation_report.json`。
- 保留：PointCloudValidator、MapValidator、ProductionParamGate。停用後會改 selected candidate、dominant layer 或正式問題判斷。
- 刪除：UnityParamGate、UnityImporter。停用後 latest sfm/train/export 的正式 decision / next_action / selected candidate / dominant layer 不產生必要改善；production 端也未讀取 decision-layer 的 `unity_export_params.json` 或 `import_summary.json` 作正式接口。
- 已修正：coordinator 會在 pack 未寫出 `phase0_report.json` 時，依 pack_result、validation_report 與 decision_log 生成正式 `phase0_report.json`，再交給 current_state / arbiter / shared decision 使用。
- 驗證：2026-05-05 replay latest train/export 後，train = `hold_export` + selected `PPG-001` + dominant `parameter`；export = `hold_phase_close` + selected `PPG-001` + dominant `parameter`。
- 已整理：ArtifactResolver 統一 contract artifact alias / fallback；Phase0ReportGenerator 統一 phase0_report 生成規則。兩者仍留在 `coordinator.py` 內，不新增核心檔，避免 6-core 膨脹。
- 已整理：ProblemLayerAnalyzer 統一 problem_layer 單筆推斷與 candidate aggregation；`candidate_pool.py` 負責單一規則來源，`current_state.py` 只消費聚合結果。

---

## 2026-05-01 — Outcome Label CLI

- 人工標籤不得手改 JSON；必須使用 `run_phase0.py --label-feedback <outcome_feedback.json>`。
- 可標記欄位：`--decision-useful`、`--metrics-improved`、`--problem-layer-correct`、`--human-override`、`--wasted-run`、`--repeated-problem`、`--critical-bad-release`。
- bool 值接受 `true / false / none`，也接受 `yes / no`。
- CLI 會更新該 `outcome_feedback.json`，並重算同一 stage 目錄下的 `learning_curve.json`。
- 範例：`python run_phase0.py --label-feedback D:\agent_test\outputs\phase0\<run_id>\train_complete\outcome_feedback.json --decision-useful false --human-override true --wasted-run true --label-source human_review --label-note "manual review rejected"`。

---

## 2026-05-01 — Learning Curve 閉環

- `coordinator.py` 每輪寫出 `outcome_feedback.json` 後，會同步產生 `learning_curve.json`。
- `outcome_feedback.json` 現在包含 preliminary outcome label：`decision_useful`、`human_override`、`wasted_run`、`repeated_problem`、`critical_bad_release`、`token_cost_estimate`。
- `candidate_pool.py` 會讀取歷史 feedback；若已有人工或後續結果標籤，優先使用 `effectiveness_rate`，否則退回 `accepted_rate` 影響 `rank_score`。
- `adapters/adaptive_threshold.py` 已接上正式 audit root：優先讀 `outputs/phase0/*/*/outcome_feedback.json` 重建 metric history，並保留 `phase0_decisions.log` 當舊格式 fallback。
- `arbiter.py` 的 hold-path 已接上 `rank_score`；同一 `problem_layer` 內若有多個候選，arbiter 會選較高分候選，不再固定硬編碼單一 ID。
- `ProductionParamGate` 已改成真 gate：只有產出可執行的 `orchestrated_rerun` 計畫時才會 `approved=true`；若僅是維持現況或缺資料，則回 `hold_manual_review`。
- `ProductionParamGate.evaluate()` 會回傳正式 `gate_status / reason / sfm_profile / train_profile`，不再只提供永遠通過的布林值。
- `map_building_pack.py` 會依 gate 結果寫出 `production_params_ready`、`production_params_hold`、`production_params_failed`；只有 ready path 才代表 pack 已產出可直接執行的 rerun 參數。
- `learning_curve.json` 用於判斷對話框 AI 是否可從 meta-evaluator 降為 observer-only；目前未達標，因 latest train/export replay 都仍是 `held_for_review` 且尚未標籤。

---

## 2026-05-01 — Ablation 刪除結果（第一輪）

- 驗證方法：以 latest train/export contract 跑 baseline，再逐一停用非核心 stage，比較 `decision / next_action / selected_candidate_id / dominant_layer`。
- 結果：`RecoveryAdvisor` 與 `PhaseReporter` 停用後正式 decision 不變，只少支援型候選與報告輸出。
- 處置：兩者已從 runtime、`agents.phase0.__all__` 與測試移除。
- 現行 map-building pack stage：PointCloudValidator、MapValidator、ProductionParamGate。

---

## 2026-04-30 — Problem Layer Signal

- pack 輸出候選時必須標記 `problem_layer`，分類只允許 `data`、`parameter`、`framework`。
- candidate pool 優先讀明確欄位，避免只靠自然語言關鍵字推斷。
- current state 的 dominant layer 是 root-cause signal，不是候選數量投票。
- latest train/export contract replay 已驗證：目前阻塞歸類為 `parameter`，arbiter 會導向 `review_training` / `review_export`，而不是誤判為 framework switch。
