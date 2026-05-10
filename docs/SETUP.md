# SETUP — 決策層 install / label / replay

> 此檔案聚集 install SOP、Outcome Label CLI、與 replay workflow。原本散在 `.instructions.md` / `docs/README.md` / `docs/CHANGELOG.md`，這裡是單一入口。

## 1. 安裝

### 1.1 環境
- Python 3.10+（決策層只用標準庫 + 4 個輕依賴）
- Windows / Linux / macOS 均可（決策層本身跨平台；只有與生產層的 JSON 檔案路徑預設指向 Windows `C:\3d-recon-pipeline` 與 `D:\agent_test`）

### 1.2 步驟

```bash
git clone https://github.com/e1134171019/agent_3D.git
cd agent_3D

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 1.3 驗證設定

```bash
python run_phase0.py --verify
```

`--verify` 會檢查決策層配置與生產層輸出根目錄。Linux / macOS 上若預設 Windows 路徑不存在會 SKIP 該檢查（見 [`docs/CHANGELOG.md`](CHANGELOG.md)）。

## 2. 跑一次決策（單一 contract）

生產層的 `latest_train_complete.json` 寫好後：

```bash
python run_phase0.py --contract C:\3d-recon-pipeline\outputs\agent_events\latest_train_complete.json
```

輸出：
- `D:\agent_test\outputs\phase0\<run_id>\train_complete\arbiter_decision.json` 等 6-core JSON
- `C:\3d-recon-pipeline\outputs\agent_decisions\latest_train_decision.json`（回寫給生產層）

替換 `latest_train_complete.json` 為 `latest_sfm_complete.json` 或 `latest_export_complete.json` 跑其他 stage。

## 3. Watch 模式（即時反應生產層）

```bash
python run_phase0.py --watch
```

每 3 秒輪詢 `outputs/agent_events`，偵測到新 contract 自動跑決策。生產層的 `train_3dgs.py` / `export_ply_unity.py` 寫完 contract 後也會用 subprocess 呼叫一次 `run_phase0.py`，watch 模式只是雙保險。

調整輪詢頻率：`--poll-seconds 5.0`。

## 4. Outcome Label CLI（人工標籤）

人工標籤**不得**手改 JSON，必須用 CLI：

```bash
python run_phase0.py --label-feedback D:\agent_test\outputs\phase0\<run_id>\train_complete\outcome_feedback.json \
  --decision-useful false \
  --human-override true \
  --wasted-run true \
  --label-source human_review \
  --label-note "manual review rejected"
```

### 4.1 可標記欄位

| flag | 意義 |
|---|---|
| `--decision-useful` | 此次決策是否有用 |
| `--metrics-improved` | 決策後 metric 是否改善 |
| `--problem-layer-correct` | 選的 problem layer 是否正確 |
| `--human-override` | 是否需人工覆寫 |
| `--wasted-run` | 是否造成廢跑 |
| `--repeated-problem` | 是否重複既有問題 |
| `--critical-bad-release` | 是否導致重大壞 release |

### 4.2 接受值

`true / false / none`，也接受 `yes / no`。

### 4.3 副作用

CLI 會更新該 `outcome_feedback.json`，並重算同一 stage 目錄下的 `learning_curve.json`。

## 5. Replay 既有 contract（驗證 / debug）

直接傳歷史 contract 路徑：

```bash
python run_phase0.py --contract D:\agent_test\outputs\phase0\<run_id>\train_complete\input_contract.json
```

決策層每次跑都會把該次的輸入 contract 複製到 `outputs/phase0/<run_id>/<stage>/input_contract.json`，方便事後 replay。

## 6. 自訂路徑

決策層所有路徑可用 CLI flag 覆寫：

```bash
python run_phase0.py --watch \
  --production-root /home/me/my-3d-recon-pipeline/outputs \
  --events-root /home/me/my-3d-recon-pipeline/outputs/agent_events \
  --output-root /home/me/my-agent_test/outputs/phase0 \
  --decisions-root /home/me/my-3d-recon-pipeline/outputs/agent_decisions
```

## 7. 常見問題

### `--verify` 在 Linux / macOS 失敗
預設路徑指向 Windows `C:\` / `D:\`。Linux / macOS 上要顯式覆寫（見 §6），或忽略 `--verify` 直接跑 `--contract`。

### 決策層失敗影響生產層嗎？
不會。生產層用 `subprocess` 呼叫 `run_phase0.py`，失敗不阻斷生產主線。詳見生產層 [`docs/_governance.md`](https://github.com/e1134171019/3d-recon-pipeline/blob/main/docs/_governance.md)。

### 怎麼開發新 pack stage？
先看 [`CONTRIBUTING.md`](../CONTRIBUTING.md) §2 Ablation 測試流程。
