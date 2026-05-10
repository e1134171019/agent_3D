# agent_test README

> 角色：`D:\agent_test` 是決策層，讀生產層的 `outputs/agent_events/latest_*_complete.json`，輸出 `outputs/agent_decisions/latest_*_decision.json`。

## 正式核心 6 個模組

- `src/contract_io.py`
- `src/coordinator.py`
- `src/candidate_pool.py`
- `src/current_state.py`
- `src/arbiter.py`
- `src/outcome_feedback.py`

## 其他檔案分工

- `src/map_building_pack.py`：map-building pack orchestration
- `src/shared_decision_mapper.py`：shared outbox translation
- `src/phase0_runner.py`、`run_phase0.py`：entry / watch / launcher
- `agents/phase0/*`：map-building strategy pack
- `agents/quality/*`：quality strategy pack
- `adapters/pytorch_decision_model.py`：離線 PyTorch 學習器，從 `outcome_feedback.json` 訓練 `decision_useful` 分類器
- `outputs/*`：審計與覆蓋率報告
- `archive/*`：歷史封存，不作正式升級依據

## 升級規則（最小集合）

升級 agent 時，先改核心 6 模組；pack stage 必須通過 ablation 證明會影響正式 decision 才保留。

目前訊號規則：
- `problem_layer` 由 pack 明確提供，core 只收斂與裁決。
- root-cause dominant layer 只計入診斷候選，避免支援候選污染主因判斷。

## 驗證 runtime

執行 `run_phase0.py --contract <latest_*_complete.json>` 後檢查：
- `current_state.json`
- `candidate_pool.json`
- `arbiter_decision.json`
- `outcome_feedback.json`

## 詳細規格與最新變更

- [`AGENT_SYSTEM_V1.md`](AGENT_SYSTEM_V1.md)：6-core + pack 結構**正式規格**（不含 dated change）
- [`CHANGELOG.md`](CHANGELOG.md)：ablation 紀錄、Learning Curve 閉環、Outcome Label CLI、Offline Teacher 規則、Runtime Consistency 修正等所有 dated changes
- [`DECISION_DATASET_SCHEMA.md`](DECISION_DATASET_SCHEMA.md)：offline learning 資料 schema
