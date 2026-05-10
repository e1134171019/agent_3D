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
- `adapters/pytorch_decision_model.py`：離線 PyTorch 學習器，從 `outcome_feedback.json` 訓練 `decision_useful` 分類器
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
- `adapters/adaptive_threshold.py` 現在優先使用正式 `outcome_feedback` 歷史計算品質閾值，`learning_curve` 作為同一 audit root 的學習摘要；只有缺少正式 feedback 時才回退舊 `phase0_decisions.log`。
- `arbiter.py` 的 hold-path 會正式吃 `rank_score`；若同一 `problem_layer` 有多個候選，現在會選分數較高者，而不是固定回傳單一候選 ID。
- `ProductionParamGate` 已不再是永遠 `approved=true` 的假 gate；現在只有在 `sfm_plan` 或 `train_plan` 真的產生可執行 rerun 參數時才會 `approved=true`，否則回 `hold_manual_review`。
- `ProductionParamGate.evaluate()` 會回傳 `gate_status / reason / sfm_profile / train_profile`。正式 gate status 目前包含：`rerun_sfm_and_train`、`rerun_sfm`、`rerun_train`、`hold_manual_review`。
- `map_building_pack.py` 對應輸出事件現在分為 `production_params_ready`、`production_params_hold`、`production_params_failed`；`production_params_hold` 代表「有判斷但沒有可執行 rerun plan」，不是執行錯誤。
- `learning_curve.json` 用於判斷對話框 AI 是否可從 meta-evaluator 降為 observer-only；目前未達標，因 latest train/export replay 都仍是 `held_for_review` 且尚未標籤。
- `adapters/pytorch_decision_model.py` 是目前第一個 ML probe：它把 `outcome_feedback` 轉成結構化特徵，離線預測 `decision_useful`。目前只允許當離線學習器 / advisory model，不直接改寫正式 `arbiter`。
- 2026-05-05 實測：`outputs/phase0` 下共 `9` 筆 feedback、其中 `8` 筆可訓練，離線訓練 accuracy 直接達到 `1.0`，代表目前樣本太少、過擬合風險高；不得把這個模型直接升格為正式裁決器。
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
- `docs/DECISION_DATASET_SCHEMA.md`：歷史 run 回填 schema 與 Qwen teacher output schema。
- `adapters/qwen_teacher.py`：本機 Ollama / Qwen teacher adapter，只做語意標註，不進正式 runtime。
- `adapters/historical_run_backfill.py`：run-level backfill schema，供歷史實驗回填與 teacher prompt 使用。
- `tests/test_pytorch_decision_model.py` 只測 deterministic feature merge；不直接呼叫本機 Ollama。

## Offline Learning 分層規則（2026-05-09）
- `Ollama / Qwen` 的正式角色是 **teacher / labeler / explainer**，不是 formal runtime arbiter。
- `PyTorch` 的正式角色是 **offline trainer**；真正學習在 `adapters/train_teacher_augmented_baseline.py` 或後續 trainer 進行，不在 `tests/test_pytorch_decision_model.py` 內進行。
- `tests/test_pytorch_decision_model.py` 只負責：
  - schema 驗證
  - feature merge 驗證
  - mocked teacher output 驗證
  - baseline train/predict 介面 sanity check
- `outputs/offline_learning/*` 是 teacher / learner / backfill 的唯一正式落點；不得把其輸出直接視為 `latest_*_decision.json`。
- 對話框 AI 只做 meta review：
  - 審查 teacher prompt 與標註品質
  - 審查 offline model 是否 leakage / overfit
  - 審查哪些 sandbox probe 值得升下一輪


## Offline Teacher / Dataset Layer
- `adapters/build_historical_run_backfill.py`：建立第一批 `historical_run_backfill_seed.jsonl`，只回填已完成且已有正式結論的 run。
- `adapters/label_historical_backfill_with_ollama.py`：使用本機 `Ollama/Qwen` 為 seed records 產生 teacher JSON，不進 formal runtime。
- `outputs/offline_learning/`：離線學習資料層，與 `outputs/phase0` 正式 feedback 分離。
- `adapters/pytorch_decision_model.py`：歷史 backfill 會先把 `issue_type` 顯式投影回 formal `problem_layer` 空間；teacher `confidence` 現在主要作為 offline training 的 sample weight，而不是主要輸入特徵。
- `adapters/pytorch_decision_model.py`：teacher `run_useful` 不得直接進 teacher feature vector；run-level supervision 與 feature space 要分離，避免 offline learner 偷讀 target。
- `adapters/pytorch_decision_model.py`：historical backfill 的 6 個 runtime-style bool 會做保守推導，不再全部硬填 `0.0`。
- `probe_context`：historical backfill 現在允許攜帶 framework-specific sandbox 上下文；目前第一個用途是 `Scaffold-GS`。
- `adapters/build_scaffold_probe_backfill.py`：把 `C:\3d-recon-pipeline\experimental\scaffold_gs_probe` 的 manifest / outputs 轉成離線 seed records。
- `adapters/label_historical_backfill_with_ollama.py`：現在會把 `probe_context` 一起送進本機 `Ollama/Qwen`，讓 teacher 能辨識 `prepared` / `trained` / `setup_blocked` 的框架 probe 狀態。

