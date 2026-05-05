"""
自適應閾值管理 - 根據正式 feedback 歷史動態調整決策門檻

設計思路：
1. 優先讀取 `outputs/phase0/*/*/outcome_feedback.json`
2. 若存在正式 feedback，根據可重用 outcome 估計品質門檻
3. 若無正式 feedback，再回退舊 `phase0_decisions.log`
4. 防止門檻偏離過遠：max/min 限制
"""

from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional

from src.contract_io import read_json_records
from src.outcome_feedback import OutcomeFeedbackHistory


class AdaptiveThreshold:
    """
    自適應閾值計算引擎
    
    使用方式：
        threshold = AdaptiveThreshold("outputs/phase0/phase0_decisions.log")
        dynamic_psnr_threshold = threshold.get_threshold("psnr", base=20.0)
    """
    
    def __init__(self, log_path: str, window: int = 10):
        """
        初始化
        
        Args:
            log_path: `outputs/phase0`、`learning_curve.json`、`outcome_feedback.json`
                或舊 `phase0_decisions.log` 的路徑
            window: 用於計算適應閾值的歷史窗口大小（最近 N 次記錄）
        """
        self.log_path = Path(log_path)
        self.window = window
        self.history = []
        self.learning_curve = {}
        self.history_source = "none"
        self._load_history()
    
    def _load_history(self):
        """優先從正式 feedback 載入，否則回退舊格式歷史記錄"""
        feedback_records = self._load_feedback_history()
        if feedback_records:
            self.history = feedback_records
            self.history_source = "outcome_feedback"
            return

        try:
            self.history = read_json_records(self.log_path)
            self.history_source = "legacy_log" if self.history else "none"
        except Exception as e:
            print(f"警告：無法讀取歷史記錄 {self.log_path}: {e}")
            self.history = []
            self.history_source = "none"

    def _resolve_audit_root(self) -> Optional[Path]:
        """由輸入路徑推導 `outputs/phase0` audit root。"""
        path = self.log_path
        if path.is_dir():
            return path

        name = path.name.lower()
        if name == "phase0_decisions.log":
            return path.parent
        if name in {"learning_curve.json", "outcome_feedback.json"} and len(path.parents) >= 3:
            return path.parents[2]
        return None

    def _load_feedback_history(self) -> List[dict]:
        """從正式 outcome_feedback / learning_curve 載入歷史記錄。"""
        audit_root = self._resolve_audit_root()
        if audit_root is None or not audit_root.exists():
            return []

        history = OutcomeFeedbackHistory(audit_root)
        records = history.load_records()
        if not records:
            return []

        self.learning_curve = history.build_learning_curve(window=self.window)
        normalized = []
        for record in records:
            metrics = record.get("observed_metrics", {}).get("contract_metrics", {})
            if not isinstance(metrics, dict) or not metrics:
                continue
            normalized.append(
                {
                    "metrics": metrics,
                    "overall_pass": record.get("outcome_status") == "accepted",
                    "decision_useful": record.get("decision_useful"),
                    "metrics_improved": record.get("metrics_improved"),
                    "human_override": bool(record.get("human_override", False)),
                    "wasted_run": bool(record.get("wasted_run", False)),
                    "critical_bad_release": bool(record.get("critical_bad_release", False)),
                    "recorded_at": record.get("recorded_at"),
                }
            )
        return normalized

    @staticmethod
    def _is_effective_record(record: dict) -> bool:
        """判斷一筆歷史是否可用於調整正式門檻。"""
        if bool(record.get("wasted_run", False)) or bool(record.get("critical_bad_release", False)):
            return False

        useful = record.get("decision_useful")
        if isinstance(useful, bool):
            return useful

        improved = record.get("metrics_improved")
        if isinstance(improved, bool):
            return improved

        return bool(record.get("overall_pass")) or record.get("action") == "approved"
    
    def get_threshold(
        self, 
        metric: str, 
        base: float,
        min_threshold: Optional[float] = None,
        max_threshold: Optional[float] = None,
        penalty: float = 1.0
    ) -> float:
        """
        計算動態閾值
        
        Args:
            metric: 指標名稱 ("psnr", "ssim", "lpips")
            base: 基礎（硬編碼）閾值
            min_threshold: 最小允許閾值（防止太倉促）
            max_threshold: 最大允許閾值（防止過度要求）
            penalty: 調整幅度加權係數，0.5 表示半速調整，1.0 表示全速
        
        Returns:
            float: 推薦的動態閾值
        """
        # 如果歷史數據不足，用基礎閾值
        if len(self.history) < 3:
            return base
        
        # 篩選過去的成功案例
        recent_successful = self._extract_recent_successful_metrics(metric)
        
        if not recent_successful or len(recent_successful) < 2:
            return base
        
        # 計算動態閾值
        hist_mean = mean(recent_successful)
        hist_stdev = stdev(recent_successful) if len(recent_successful) > 1 else 0
        
        # 根據指標類型決定調整方向
        if metric in ["ssim"]:
            # SSIM 越高越好：動態閾值 = 平均 - 1個標差（寬鬆）
            dynamic = hist_mean - 1.0 * hist_stdev * penalty
        elif metric in ["lpips"]:
            # LPIPS 越低越好：動態閾值 = 平均 + 1個標差（寬鬆，允許更高的值）
            dynamic = hist_mean + 1.0 * hist_stdev * penalty
        else:
            # PSNR 越高越好：動態閾值 = 平均 - 1個標差（寬鬆）
            dynamic = hist_mean - 1.0 * hist_stdev * penalty
        
        # 應用 min/max 限制
        if min_threshold is not None:
            dynamic = max(dynamic, min_threshold)
        if max_threshold is not None:
            dynamic = min(dynamic, max_threshold)
        
        # 防止偏離基礎閾值太遠（最多 ± 50%）
        lower_bound = base * 0.5
        upper_bound = base * 1.5
        dynamic = max(lower_bound, min(dynamic, upper_bound))
        
        return dynamic
    
    def _extract_recent_successful_metrics(self, metric: str) -> List[float]:
        """
        從歷史中提取最近的成功案例對應的指標值
        
        Args:
            metric: 指標名稱 ("psnr", "ssim", "lpips")
        
        Returns:
            List[float]: 成功案例的指標值列表
        """
        values = []
        
        for record in self.history[-self.window:]:
            try:
                # 嘗試從 validation_report 中提取
                if "metrics" in record and metric in record["metrics"]:
                    val = record["metrics"][metric]
                    if self._is_effective_record(record):
                        values.append(float(val))
            except (KeyError, ValueError, TypeError):
                continue
        
        return values
    
    def get_quality_score(self, psnr: float, ssim: float, lpips: float) -> float:
        """
        計算加權品質分數
        
        加權公式：
            quality = (PSNR / 50) * 0.3 + SSIM * 0.35 + (1 - LPIPS / 0.15) * 0.35
        
        Returns:
            float: 0-1 範圍的品質分數
        """
        psnr_score = min(psnr / 50.0, 1.0) * 0.3
        ssim_score = min(ssim, 1.0) * 0.35
        lpips_score = max(1.0 - lpips / 0.15, 0.0) * 0.35
        
        return psnr_score + ssim_score + lpips_score
    
    def get_trend(self, metric: str, window: Optional[int] = None) -> Optional[str]:
        """
        分析指標趨勢
        
        Args:
            metric: 指標名稱
            window: 回溯窗口（若 None 則用預設 window）
        
        Returns:
            "improving" | "declining" | "stable" | None
        """
        if window is None:
            window = self.window
        
        recent = self._extract_recent_successful_metrics(metric)
        
        if len(recent) < 3:
            return None
        
        recent_subset = recent[-window:]
        if len(recent_subset) < 2:
            return None
        
        # 計算一階差分
        diffs = [recent_subset[i+1] - recent_subset[i] for i in range(len(recent_subset)-1)]
        avg_diff = mean(diffs)
        
        if abs(avg_diff) < 0.01:  # 變化不到 1%
            return "stable"
        elif avg_diff > 0:
            # PSNR/SSIM 上升，LPIPS 下降 = improving（取決於指標方向）
            if metric in ["lpips"]:
                return "declining" if avg_diff > 0 else "improving"
            else:
                return "improving"
        else:
            if metric in ["lpips"]:
                return "improving" if avg_diff < 0 else "declining"
            else:
                return "declining"
    
    def recommend_action(self, metric: str, value: float, base_threshold: float) -> str:
        """
        根據趨勢給出建議
        
        Returns:
            "approve" | "investigate" | "retrain"
        """
        trend = self.get_trend(metric)
        adaptive_threshold = self.get_threshold(metric, base_threshold)
        
        # 如果所有歷史數據都失敗了
        if not self._extract_recent_successful_metrics(metric):
            return "investigate"
        
        # 根據當前值與適應閾值的關係決定
        if metric in ["lpips"]:
            passes_adaptive = value < adaptive_threshold
        else:
            passes_adaptive = value > adaptive_threshold
        
        if not passes_adaptive:
            if trend == "improving":
                return "retrain"  # 趨勢向好但未達標 → 繼續訓練
            else:
                return "investigate"  # 趨勢不好 → 診斷問題
        else:
            return "approve"  # 達到適應閾值 → 批准
