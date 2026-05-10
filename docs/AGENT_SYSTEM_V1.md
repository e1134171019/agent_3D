# Agent System V1

目前 `D:\agent_test` 採用「6-core + pack」結構。

## 正式核心（6）
1. `contract_io.py`
2. `coordinator.py`
3. `candidate_pool.py`
4. `current_state.py`
5. `arbiter.py`
6. `outcome_feedback.py`

## 非核心需通過 ablation 才能保留
- `map_building_pack.py`：pack 協調器
- `shared_decision_mapper.py`：production-facing decision payload 映射
- `phase0_runner.py` / `run_phase0.py`：啟動與 watch
- `agents/phase0/*`：map-building pack 細節；只保留會影響候選或 arbiter decision 的 stage
- `agents/quality/coverage_strategy.py`：coverage quality strategy
- `adapters/adaptive_threshold.py`：pack adapter

## 清理原則
- 核心升級只以 6 個正式模組為主
- pack / adapter / audit 不混入核心設計討論
- archive / support-only stage 不再預設保留；不影響正式 decision 者刪除
## Problem Layer Signal（2026-04-30）
- pack 輸出候選時必須標記 `problem_layer`，分類只允許 `data`、`parameter`、`framework`。
- candidate pool 優先讀明確欄位，避免只靠自然語言關鍵字推斷。
- current state 的 dominant layer 是 root-cause signal，不是候選數量投票。
- latest train/export contract replay 已驗證：目前阻塞歸類為 `parameter`，arbiter 會導向 `review_training` / `review_export`，而不是誤判為 framework switch。


## Ablation 刪除結果（2026-05-01）
- 驗證方法：以 latest train/export contract 跑 baseline，再逐一停用非核心 stage，比較 `decision / next_action / selected_candidate_id / dominant_layer`。
- 結果：`RecoveryAdvisor` 與 `PhaseReporter` 停用後正式 decision 不變，只少支援型候選與報告輸出。
- 處置：兩者已從 runtime、`agents.phase0.__all__` 與測試移除。
- 現行 map-building pack stage：PointCloudValidator、MapValidator、ProductionParamGate。
## Learning Curve 閉環（2026-05-01）
- `coordinator.py` 每輪寫出 `outcome_feedback.json` 後，會同步產生 `learning_curve.json`。
- `outcome_feedback.json` 現在包含 preliminary outcome label：`decision_useful`、`human_override`、`wasted_run`、`repeated_problem`、`critical_bad_release`、`token_cost_estimate`。
- `candidate_pool.py` 會讀取歷史 feedback；若已有人工或後續結果標籤，優先使用 `effectiveness_rate`，否則退回 `accepted_rate` 影響 `rank_score`。
- `adapters/adaptive_threshold.py` 已接上正式 audit root：優先讀 `outputs/phase0/*/*/outcome_feedback.json` 重建 metric history，並保留 `phase0_decisions.log` 當舊格式 fallback。
- `arbiter.py` 的 hold-path 已接上 `rank_score`；同一 `problem_layer` 內若有多個候選，arbiter 會選較高分候選，不再固定硬編碼單一 ID。
- `ProductionParamGate` 已改成真 gate：只有產出可執行的 `orchestrated_rerun` 計畫時才會 `approved=true`；若僅是維持現況或缺資料，則回 `hold_manual_review`。
- `ProductionParamGate.evaluate()` 會回傳正式 `gate_status / reason / sfm_profile / train_profile`，不再只提供永遠通過的布林值。
- `map_building_pack.py` 會依 gate 結果寫出 `production_params_ready`、`production_params_hold`、`production_params_failed`；只有 ready path 才代表 pack 已產出可直接執行的 rerun 參數。
- `learning_curve.json` 用於判斷對話框 AI 是否可從 meta-evaluator 降為 observer-only；目前未達標，因 latest train/export replay 都仍是 `held_for_review` 且尚未標籤。
## Outcome Label CLI（2026-05-01）
- 人工標籤不得手改 JSON；必須使用 `run_phase0.py --label-feedback <outcome_feedback.json>`。
- 可標記欄位：`--decision-useful`、`--metrics-improved`、`--problem-layer-correct`、`--human-override`、`--wasted-run`、`--repeated-problem`、`--critical-bad-release`。
- bool 值接受 `true / false / none`，也接受 `yes / no`。
- CLI 會更新該 `outcome_feedback.json`，並重算同一 stage 目錄下的 `learning_curve.json`。
- 範例：`python run_phase0.py --label-feedback D:\agent_test\outputs\phase0\<run_id>\train_complete\outcome_feedback.json --decision-useful false --human-override true --wasted-run true --label-source human_review --label-note "manual review rejected"`。


## 2026-05-01 第二輪 stage ablation
- 驗證報告：C:\tmp\agent_stage_ablation\stage_ablation_report.json。
- 保留：PointCloudValidator、MapValidator、ProductionParamGate。停用後會改 selected candidate、dominant layer 或正式問題判斷。
- 刪除：UnityParamGate、UnityImporter。停用後 latest sfm/train/export 的正式 decision / next_action / selected candidate / dominant layer 不產生必要改善；production 端也未讀取 decision-layer 的 unity_export_params.json 或 import_summary.json 作正式接口。
- 已修正：coordinator 會在 pack 未寫出 phase0_report.json 時，依 pack_result、validation_report 與 decision_log 生成正式 phase0_report.json，再交給 current_state / arbiter / shared decision 使用。
- 驗證：2026-05-05 replay latest train/export 後，train = hold_export + selected PPG-001 + dominant parameter；export = hold_phase_close + selected PPG-001 + dominant parameter。
- 已整理：ArtifactResolver 統一 contract artifact alias / fallback；Phase0ReportGenerator 統一 phase0_report 生成規則。兩者仍留在 coordinator.py 內，不新增核心檔，避免 6-core 膨脹。
- 已整理：ProblemLayerAnalyzer 統一 problem_layer 單筆推斷與 candidate aggregation；candidate_pool.py 負責單一規則來源，current_state.py 只消費聚合結果。

## Offline Teacher / Dataset Layer（2026-05-06）
- 正式 6-core runtime 不變。
- 本機 Ollama / Qwen 只作 teacher / labeler / explainer，不直接參與正式 arbiter runtime。
- 歷史 run 回填與 teacher 輸出格式，統一以 `docs/DECISION_DATASET_SCHEMA.md` 為準。
- `tests/test_pytorch_decision_model.py` 僅允許 deterministic mocked teacher 輸出；不得在測試內直接呼叫 Ollama 或要求下載 Qwen / TabPFN 套件。
- 真正的離線學習入口是 `adapters/train_teacher_augmented_baseline.py` 或後續 trainer，不是 `tests/test_pytorch_decision_model.py`。
- offline learner 讀到 `issue_type` 時，必須先顯式投影回 formal `problem_layer` 空間；teacher `confidence` 只作 sample weight，不得偷渡成 formal runtime 決策欄位。
- offline learner 不允許把 teacher `run_useful` 直接當輸入特徵；該欄位只屬於 run-level supervision，不屬於 feature space。
- historical backfill 轉 base vector 時，runtime-style bool 必須做保守推導，避免整排固定 `0.0` 造成資訊真空。
- 對話框 AI 角色是 meta evaluator / reviewer：審查 teacher prompt、schema、feature 與模型報告，不直接取代 formal runtime。

## Offline Teacher / Dataset Layer
- `adapters/build_historical_run_backfill.py`：建立第一批 `historical_run_backfill_seed.jsonl`，只回填已完成且已有正式結論的 run。
- `adapters/label_historical_backfill_with_ollama.py`：使用本機 `Ollama/Qwen` 為 seed records 產生 teacher JSON，不進 formal runtime。
- `adapters/train_teacher_augmented_baseline.py`：正式 offline trainer，負責吸收 backfill + teacher labels；不得直接改寫 `latest_*_decision.json`。
- `outputs/offline_learning/`：離線學習資料層，與 `outputs/phase0` 正式 feedback 分離。



