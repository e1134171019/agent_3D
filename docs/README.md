# agent_test README

正式核心只看 6 個模組：
- `src/contract_io.py`
- `src/coordinator.py`
- `src/candidate_pool.py`
- `src/current_state.py`
- `src/arbiter.py`
- `src/outcome_feedback.py`

其他檔案分工：
- `src/map_building_pack.py`：map-building pack orchestration
- `src/shared_decision_mapper.py`：shared outbox translation
- `src/phase0_runner.py`、`run_phase0.py`：entry / watch / launcher
- `agents/phase0/*`：map-building strategy pack
- `agents/quality/*`：quality strategy pack
- `outputs/*`：審計與覆蓋率報告
- `archive/*`：歷史封存，不作正式升級依據

升級 agent 時，先改核心 6 模組；pack stage 必須通過 ablation 證明會影響正式 decision 才保留。
目前訊號規則：
- `problem_layer` 由 pack 明確提供，core 只收斂與裁決。
- root-cause dominant layer 只計入診斷候選，避免支援候選污染主因判斷。
- 若要驗證 runtime，執行 `run_phase0.py --contract <latest_*_complete.json>` 後檢查 `current_state.json`、`candidate_pool.json`、`arbiter_decision.json`、`outcome_feedback.json`。


## 2026-05-01 精簡結果
- `RecoveryAdvisor` / `PhaseReporter` 經 ablation 驗證不影響 latest train/export 的正式 decision，已刪除。
- 現行 pack 候選來源剩 3 個：PCV、VAL、PPG。
- 後續舊實驗程式一律採同樣規則：能改變正式決策就合併，不能改變就刪除。
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
