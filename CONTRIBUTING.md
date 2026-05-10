# Contributing to agent_3D

> 此檔案聚集 PR 規則與 **ablation 紀律**。新功能進入決策層前必須通過 ablation。

## 1. 什麼東西可以加進決策層

決策層只接收三類改動：

| 類型 | 規則 | 是否需 ablation |
|---|---|---|
| **6-core** 模組改動 | 直接動 `src/{contract_io,coordinator,candidate_pool,current_state,arbiter,outcome_feedback}.py` | 不需 ablation，但需在 [`docs/CHANGELOG.md`](docs/CHANGELOG.md) 留紀錄 |
| **Pack stage** 新增（`agents/phase0/*`、`agents/quality/*`）| 必須通過 ablation 測試才能保留 | **必須** |
| **Adapter / audit / archive** | 不得影響正式 `arbiter_decision`；不影響者可保留 | 不影響者免，影響者必須 |

非以上三類（例如「新增一個 dialog AI 規則」、「改 teacher prompt」）屬於 offline learning，與正式 runtime 隔離，請見 [`docs/CHANGELOG.md` § 2026-05-06 Offline Teacher / Dataset Layer](docs/CHANGELOG.md)。

## 2. Ablation 測試流程

新增 pack stage 或修改既有 pack stage，必須跑 ablation：

```
1. 以 latest train/export contract 跑 baseline，記錄正式
   arbiter_decision.{decision, next_action, selected_candidate_id, dominant_layer}
2. 停用該 stage（或不加入），重跑同一份 contract
3. 比較兩次正式 arbiter_decision
4. 若停用後正式 arbiter_decision 不變 → 該 stage 不應保留（刪除）
5. 若停用後正式 arbiter_decision 變化 → 該 stage 通過 ablation，可保留
6. 在 docs/CHANGELOG.md 新增 dated 章節，列出：
   - 報告路徑（建議 C:\tmp\agent_stage_ablation\stage_ablation_report.json）
   - 保留 / 刪除清單與理由
```

歷史 ablation 案例見 [`docs/CHANGELOG.md` § 2026-05-01 Ablation 刪除結果（第一輪）](docs/CHANGELOG.md) 與 § 第二輪 stage ablation。

## 3. PR 規則

### 3.1 一個 PR 只做一件事

- 不混 6-core 改動 + pack stage 新增
- 不混 spec 改動（AGENT_SYSTEM_V1.md）+ dated 紀錄（CHANGELOG.md）；**spec 修改用 PR**，**dated 紀錄用 PR**

### 3.2 必改清單（依改動類型）

| 改動類型 | 必改檔案 |
|---|---|
| 6-core contract 變更 | `src/{module}.py` + `docs/AGENT_SYSTEM_V1.md`（spec）+ `docs/CHANGELOG.md`（dated）+ `docs/DECISION_DATASET_SCHEMA.md`（若 schema 變）|
| 新增 pack stage（通過 ablation）| `agents/{phase0,quality}/{name}.py` + `docs/CHANGELOG.md` + 對應測試 |
| 停用 pack stage | 刪 `agents/{phase0,quality}/{name}.py` + 從 `__all__` / 測試移除 + `docs/CHANGELOG.md` 留 ablation 報告路徑 |
| 入口（人類 / AI）調整 | `README.md`（root）/ `docs/README.md` / `.instructions.md` |

### 3.3 commit message 格式

```
<type>: <短摘要>

<為什麼>
<改了什麼>
<驗證方式（含 ablation 報告路徑）>
```

`<type>` ∈ `{feat, fix, docs, refactor, test, chore}`。

## 4. 禁止項

- **不得**在 `tests/test_pytorch_decision_model.py` 直接呼叫 Ollama 或下載 Qwen / TabPFN（測試只允許 deterministic mocked teacher 輸出）
- **不得**手改 `outcome_feedback.json`；必須使用 `python run_phase0.py --label-feedback ...`
- **不得**把 teacher `run_useful` 直接當輸入特徵；run-level supervision 不可進 feature space
- **不得**把 teacher `confidence` 偷渡成 formal runtime 決策欄位（只能作 sample weight）
- **不得**在 6-core 內讀 pack 內部狀態；改 pack 不得反向改 6-core contract

## 5. 提交前 checklist

- [ ] 改動屬於三類之一（6-core / pack / adapter）
- [ ] 若涉及 pack，已跑 ablation 測試並留報告
- [ ] 已在對應文件留紀錄（spec → AGENT_SYSTEM_V1.md，dated → CHANGELOG.md）
- [ ] 沒有違反第 4 節禁止項
- [ ] PR 描述含「為什麼 / 改什麼 / 驗證方式」三段
