# 🔗 兩層架構接通方案

**日期**: 2026-04-05  
**狀態**: ✅ **已實現**

---

## 📊 架構概覽

```
┌──────────────────────────────────────────────────────────────┐
│  D:\agent_test (第二層設計)                                   │
│  多 Agent 自動化框架 + 8 級別驗證系統                          │
├──────────────────────────────────────────────────────────────┤
│  • Runner (主控制器)                                           │
│  • 8 個獨立 Agent                BUILD/TEST/TRAIN/ANALYZE...  │
│  • Adapters (介面層)             ↓                           │
│  • Event Bus + State Manager     新增: recon_pipeline_adapter│
└──────────────────────────────────────────────────────────────┘
                         ↓
         ┌───────────────────────────────────────┐
         │  recon_pipeline_adapter (新增)         │
         │  • run_complete_pipeline()            │
         │  • run_sfm_reconstruction()           │
         │  • run_3dgs_training()                │
         │  • run_export_ply()                   │
         └───────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│  C:\3d-recon-pipeline (第一層實現)                            │
│  具體 3D 重建管道                                             │
├──────────────────────────────────────────────────────────────┤
│  [Phase 0] 訊影格抽取                 extract_frames.py      │
│  [Phase 1] 批量縮圖                   downscale_frames.py    │
│  [Phase 2] SfM 重建 (COLMAP)          sfm_colmap.py          │
│  [Phase 3] 3DGS 訓練 (改善版)        train_3dgs_improved.py │
│  [Phase 4] 匯出模型                   export_*.py            │
└──────────────────────────────────────────────────────────────┘
```

---

## 🚀 新增檔案

### 1. `D:\agent_test\adapters\recon_pipeline_adapter.py` (NEW)

**功能**: 將 c:\3d-recon-pipeline 包裝為適配器

```python
# 核心函數

def run_sfm_reconstruction(frames_dir, work_dir) → (success, result_dict)
    # 執行 COLMAP SfM 重建

def run_3dgs_training(frames_1k_dir, sparse_dir, output_dir, quality) → (success, result_dict)
    # 執行改善版 3DGS 訓練（防稀疏參數）

def run_export_ply(ckpt_path, output_dir) → (success, result_dict)
    # 匯出 PLY 點雲模型

def run_complete_pipeline(...) → (success, result_dict)
    # 一鍵執行完整管道（SfM → 3DGS → Export）
```

**特點**:
- 自動調用 `C:\3d-recon-pipeline\.venv\Scripts\python.exe`
- 已安裝 COLMAP 在 `C:\3d-recon-pipeline\colmap\...`
- 返回 (success, result_dict) 格式一致性
- 支援 4 個質量等級: low/medium/high/ultra

---

## 🔧 修改的檔案

### 2. `D:\agent_test\agents\trainer\agent.py` (MODIFIED)

**改動**:
- 新增 `run()` 判斷邏輯：根據 `state.pipeline_mode` 選擇訓練模式
- 原有邏輯重構為 `_run_gsplat_internal(state)` 函數
- 新增 `_run_recon_pipeline(state)` 函數

**工作流**:
```
run(state)
├─ if state.pipeline_mode == "recon_pipeline":
│  └─ _run_recon_pipeline(state)  [新增]
│     ├─ from adapters.recon_pipeline_adapter import run_complete_pipeline
│     ├─ success, result = run_complete_pipeline(...)
│     └─ return True/False
│
└─ else (默認 "gsplat"):
   └─ _run_gsplat_internal(state)  [原有邏輯]
```

---

### 3. `D:\agent_test\core\runner.py` (MODIFIED)

**改動**:
- `run()` 方法開始時新增管道選擇菜單
- 新增 `_run_recon_pipeline_mode(state)` 方法

**工作流**:
```
Runner.run()
├─ 顯示菜單:
│  ├─ [1] 內部 gsplat 模式 (原有)
│  └─ [2] 完整 recon_pipeline (新增)
│
├─ if 選擇 == 2:
│  ├─ state.pipeline_mode = "recon_pipeline"
│  ├─ 詢問訓練質量 (low/medium/high/ultra)
│  └─ self._run_recon_pipeline_mode(state)  [新增]
│
└─ else:
   └─ 原有 Level 5A/5B/5C 邏輯
```

---

### 4. `D:\agent_test\adapters\__init__.py` (MODIFIED)

**改動**:
```python
# 新增導入
from .recon_pipeline_adapter import (
    run_complete_pipeline,
    run_sfm_reconstruction,
    run_3dgs_training,
    run_export_ply
)
```

---

## 📋 使用方式

### 選項 A: 使用內部 gsplat 模式（原有）

```bash
cd D:\agent_test
python main.py
# 選擇 [1] 或按 Enter 默認
# 執行 Level 5A/5B/5C 驗證
```

---

### 選項 B: 使用 recon_pipeline 完整管道（新增）

```bash
cd D:\agent_test
python main.py

# 選擇時：
# 選擇 (1/2 或按 Enter 默認): 2
# ↓
# ✅ 使用 recon_pipeline 模式
# 訓練質量 (low/medium/high/ultra，預設 high): high  [或其他]
# ↓
# 【RECON_PIPELINE】完整 3D 重建管道
# 流程: [COLMAP SfM] → [3DGS Training] → [PLY Export]
```

**流程詳解**:
1. **Build** → 環境驗證
2. **Train** → 執行完整管道：
   - COLMAP SfM 重建 (~30-60 min，取決於影框數)
   - 3DGS 訓練 (quality=high → ~25 min, RTX 5070 Ti)
   - PLY 匯出
3. **Test** → 驗證輸出
4. **Export** → 生成最終文檔
5. **Plot** → 繪圖和報告

---

## 🎯 核心改進

### 防止點雲過稀的參數

所有質量等級都已優化，focus on **density & opacity quality**:

| 參數 | low | medium | high | ultra |
|------|-----|--------|------|-------|
| 迭代 | 20k | 35k | 50k | 70k |
| 初始透度 | 0.3 | 0.5 | 0.5 | 0.6 |
| 初始尺度 | 0.8 | 0.6 | 0.5 | 0.4 |
| 透度正則 | 0.001 | 0.002 | 0.003 | 0.005 |
| SH 階數 | 2 | 3 | 3 | 4 |
| 隨機背景 | ✓ | ✓ | ✓ | ✓ |

---

## 📊 成果文檔

執行完成後自動生成:
- `docs/RECON_PIPELINE_REPORT.md` - 管道執行報告
- `logs/recon_pipeline_*.log` - 完整日誌
- `exports/3dgs_auto/ply/` - 最終 PLY 點雲

---

## ✅ 驗證清單

- [x] recon_pipeline_adapter.py 已建立
- [x] trainer/agent.py 已改為雙模式
- [x] runner.py 已添加管道選擇
- [x] 适配器 __init__.py 已更新
- [x] COLMAP 已下載到 C:\3d-recon-pipeline\colmap\
- [x] Python 環境已配置

---

## 🔗 下一步

1. **立即測試** recon_pipeline 模式：
   ```bash
   cd D:\agent_test
   python main.py
   # 選 [2]，選擇 quality=high
   ```

2. **觀察完整流程** (~2 小時):
   - SfM 重建 進度
   - 3DGS 訓練 Loss 曲線
   - 最終點雲密度診斷

3. **對比結果**:
   - 新舊訓練成果稀疏度對比
   - 診斷工具：`C:\3d-recon-pipeline\diagnose_splats.py`

---

## 🛠️ 故障排除

若 recon_pipeline 失敗：
1. 檢查 frames 已下載: `C:\3d-recon-pipeline\data\frames_1k`
2. 驗證 COLMAP: `C:\3d-recon-pipeline\colmap\COLMAP-3.8-windows-no-cuda\bin\colmap.exe --version`
3. 檢查日誌: `D:\agent_test\logs\` 最新文件

---

**創建時間**: 2026-04-05 13:45:00  
**適配版本**: agent_test v2.0 + 3d-recon-pipeline v1.4
