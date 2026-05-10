# Agent System V1

> 角色：6-core + pack 結構**正式規格**。本檔案只放穩定結構與規則，不放 dated changes。
> 變更紀錄：所有 dated changes（ablation 結果、Learning Curve 閉環、Outcome Label CLI、Offline Teacher 規則、Runtime Consistency 修正等）請見 [`CHANGELOG.md`](CHANGELOG.md)。

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

## Pack 結構與運作
- `agents/phase0/*`：map-building strategy pack（地圖建構主線）
- `agents/quality/*`：quality strategy pack（覆蓋率 / 品質）
- pack 對 6-core 的接口只有：candidate 輸出（必含 `problem_layer`）、phase0_report.json、artifact 寫出
- 6-core 不允許讀 pack 內部狀態；改 pack 不得反向改 6-core contract

## 升級規則（formal）
- 改 6-core contract → 必須先在 [`DECISION_DATASET_SCHEMA.md`](DECISION_DATASET_SCHEMA.md) 與 [`CHANGELOG.md`](CHANGELOG.md) 中記錄
- 新增 pack stage → 必須通過 ablation 測試（停用後正式 `arbiter_decision` 是否變化）才保留
- 停用 pack stage → 必須在 [`CHANGELOG.md`](CHANGELOG.md) 留 ablation 報告路徑
