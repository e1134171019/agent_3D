# agent_3D — 決策層

> 此倉為 [`3d-recon-pipeline`](https://github.com/e1134171019/3d-recon-pipeline) 的**決策層**。生產層跑「影片 → 抽幀 → COLMAP → 3DGS → PLY/Unity」實際流水線；決策層讀生產層輸出的 contract/event JSON，做 problem-layer 分類與候選選擇，輸出 `latest_*_decision.json` 回寫給生產層。

## 30 秒進入

| 你是 | 從這裡開始 |
|---|---|
| **AI 代理 / Devin** | [`/.instructions.md`](.instructions.md)（最小入口 + 6-core 規則） |
| **想看 spec** | [`docs/AGENT_SYSTEM_V1.md`](docs/AGENT_SYSTEM_V1.md)（6-core + pack 結構正式規格） |
| **想看歷史變更** | [`docs/CHANGELOG.md`](docs/CHANGELOG.md)（ablation / Learning Curve / Outcome Label CLI / Offline Teacher / Runtime Consistency） |
| **第一次安裝 / 跑** | [`docs/SETUP.md`](docs/SETUP.md)（install + label CLI + replay） |
| **想貢獻 PR** | [`CONTRIBUTING.md`](CONTRIBUTING.md)（PR 規則 + ablation 紀律） |
| **看模組分工** | [`docs/README.md`](docs/README.md) |

## 6-core 是什麼

決策層只有 6 個正式模組：

```
contract_io      → 讀生產層 latest_*_complete.json，寫 latest_*_decision.json
coordinator      → 串聯 candidate / state / arbiter，產 phase0_report
candidate_pool   → 候選收集，必含 problem_layer ∈ {data, parameter, framework}
current_state    → metrics / dominant_layer / hold reason
arbiter          → 選 candidate、定 next_action
outcome_feedback → 寫 outcome_feedback.json + learning_curve.json
```

非 6-core 模組（pack / adapter / audit）必須通過 ablation 才能保留。詳見 [`docs/AGENT_SYSTEM_V1.md`](docs/AGENT_SYSTEM_V1.md)。

## 與生產層的接口

只透過 JSON 檔案契約耦合，不是函式呼叫：

```
                生產層（C:\3d-recon-pipeline）
                 │
    寫出  outputs/agent_events/latest_{sfm,train,export}_complete.json
                 │
                 ▼
                決策層（D:\agent_test）
                 │  讀 → 6-core → 寫
                 ▼
    寫出  outputs/agent_decisions/latest_{sfm,train,export}_decision.json
                 │
                 ▼
                生產層讀回（subprocess 呼叫，失敗不阻斷）
```

完整接口規則見生產層 [`docs/_governance.md`](https://github.com/e1134171019/3d-recon-pipeline/blob/main/docs/_governance.md)。

## 最小依賴

```
pyyaml==6.0
pydantic==2.5.0
numpy==1.24.0
python-dateutil==2.8.2
```

詳細安裝步驟見 [`docs/SETUP.md`](docs/SETUP.md)。
