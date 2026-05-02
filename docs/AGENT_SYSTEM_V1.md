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
- 驗證：2026-05-01 replay latest train/export 後，train = hold_export + selected VAL-001 + dominant parameter；export = hold_phase_close + selected PPG-001 + dominant parameter。
- 已整理：ArtifactResolver 統一 contract artifact alias / fallback；Phase0ReportGenerator 統一 phase0_report 生成規則。兩者仍留在 coordinator.py 內，不新增核心檔，避免 6-core 膨脹。
- 已整理：ProblemLayerAnalyzer 統一 problem_layer 單筆推斷與 candidate aggregation；candidate_pool.py 負責單一規則來源，current_state.py 只消費聚合結果。
