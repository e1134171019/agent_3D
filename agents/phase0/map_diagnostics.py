"""
MapDiagnostics - 診斷引擎（簡化版 - 無 PyKnow 依賴）

職責：
1. 根據當前指標 + 歷史數據進行根因診斷
2. 區分 SfM 問題 vs 訓練不足 vs 參數調優
3. 生成富信息的診斷建議（不只是 PASS/FAIL）

設計思路：
使用簡潔的基於規則的系統（避免 PyKnow 兼容性問題）
"""

from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime


@dataclass
class DiagnosisResult:
    """診斷結果"""
    diagnosis: str  # 診斷名稱，如 "sparse_gaussians", "insufficient_training"
    confidence: float  # 信心度 0-1
    action: str  # 推薦行動：retry, retrain, diagnose, approve
    reason: str  # 人類易讀的解釋
    details: Dict  # 詳細數據


class MapDiagnostics:
    """
    基於規則的診斷系統（簡化版，無 PyKnow）
    
    使用方式：
        diagnostics = MapDiagnostics()
        result = diagnostics.diagnose(
            psnr=18.5, ssim=0.75, lpips=0.18,
            history_stats={"total_runs": 3, "psnr_trend": "improving"},
            training_stats={"steps_completed": 20000, "max_steps": 30000}
        )
    """
    
    def diagnose(
        self,
        psnr: float,
        ssim: float,
        lpips: float,
        history_stats: Optional[Dict] = None,
        training_stats: Optional[Dict] = None
    ) -> DiagnosisResult:
        """
        執行診斷推理
        
        Args:
            psnr: 當前 PSNR 值
            ssim: 當前 SSIM 值
            lpips: 當前 LPIPS 值
            history_stats: 歷史統計（可選）
            training_stats: 訓練狀態（可選）
        
        Returns:
            DiagnosisResult: 診斷結果
        """
        # 規則 1: 所有指標都達標
        if psnr > 20 and ssim > 0.80 and lpips < 0.15:
            return DiagnosisResult(
                diagnosis="quality_acceptable",
                confidence=0.95,
                action="approve",
                reason="所有指標都達到品質門檻，地圖可用於下一階段",
                details={"next_stage": "unity_import"}
            )
        
        # 規則 2: 首次訓練且指標很低
        if history_stats is None or history_stats.get("total_runs", 0) < 2:
            if psnr < 15:
                return DiagnosisResult(
                    diagnosis="insufficient_training",
                    confidence=0.95,
                    action="retrain",
                    reason="首次或少數次訓練且 PSNR < 15，需要更長的訓練時間",
                    details={"recommended_steps": 50000}
                )
        
        # 規則 3: PSNR 低但結構完整（SfM 問題徵象）
        if psnr < 18 and ssim > 0.75 and lpips < 0.20:
            return DiagnosisResult(
                diagnosis="sparse_gaussians",
                confidence=0.80,
                action="diagnose",
                reason="SfM 點雲可能過於稀疏，導致 PSNR 低。檢查 COLMAP 點數 > 50000",
                details={"check_item": "points3D.bin size", "expected_points": 50000}
            )
        
        # 規則 4: 所有指標都在改善，但還未達標
        if history_stats and history_stats.get("psnr_trend") == "improving":
            if training_stats and training_stats.get("steps_completed", 0) < 30000:
                if psnr > 15:
                    return DiagnosisResult(
                        diagnosis="improving_insufficient_steps",
                        confidence=0.90,
                        action="retrain",
                        reason="所有指標都在改善中，建議繼續訓練至 30000+ 步",
                        details={"recommendation": "extend_training", "suggested_steps": 40000}
                    )
        
        # 規則 5: 多次運行但保持平台（趨勢停滯）
        if history_stats and history_stats.get("total_runs", 0) > 5:
            psnr_trend = history_stats.get("psnr_trend", "unknown")
            ssim_trend = history_stats.get("ssim_trend", "unknown")
            lpips_trend = history_stats.get("lpips_trend", "unknown")
            
            if psnr_trend == "stable" and ssim_trend == "stable" and lpips_trend == "stable":
                return DiagnosisResult(
                    diagnosis="plateau_reached",
                    confidence=0.85,
                    action="diagnose",
                    reason="多次訓練指標已平台，需要調整超參數或檢查 SfM 品質",
                    details={"suggest_check": ["learning_rate", "gsplat_sh_degree", "colmap_point_cloud"]}
                )
        
        # 規則 6: 單一指標異常（LPIPS 特別高）
        if lpips > 0.30:
            return DiagnosisResult(
                diagnosis="lpips_anomaly",
                confidence=0.75,
                action="investigate",
                reason="LPIPS > 0.30（感知損失特別高），可能是光照、曝光或攝影機標定問題",
                details={"check_item": ["camera_calibration", "lighting", "frame_quality"]}
            )
        
        # 規則 7: 一般性不達標提示
        if psnr < 20 or ssim < 0.80 or lpips > 0.15:
            issue = []
            if psnr < 20:
                issue.append(f"PSNR 低 ({psnr:.1f})")
            if ssim < 0.80:
                issue.append(f"SSIM 低 ({ssim:.2f})")
            if lpips > 0.15:
                issue.append(f"LPIPS 高 ({lpips:.3f})")
            
            return DiagnosisResult(
                diagnosis="quality_insufficient",
                confidence=0.70,
                action="retrain",
                reason=f"指標未達門檻：{' + '.join(issue)}，建議繼續訓練或檢查輸入數據品質",
                details={"issues": issue}
            )
        
        # 預設診斷
        return DiagnosisResult(
            diagnosis="unknown",
            confidence=0.50,
            action="investigate",
            reason="無法確定診斷，建議手動檢查日誌",
            details={}
        )


def run_diagnosis(
    psnr: float,
    ssim: float,
    lpips: float,
    history_stats: Optional[Dict] = None,
    training_stats: Optional[Dict] = None
) -> DiagnosisResult:
    """
    快速診斷接口（保持與舊 API 兼容）
    
    Args:
        psnr: 當前 PSNR 值
        ssim: 當前 SSIM 值
        lpips: 當前 LPIPS 值
        history_stats: 歷史統計（可選）
        training_stats: 訓練狀態（可選）
    
    Returns:
        DiagnosisResult: 診斷結果
    """
    diagnostics = MapDiagnostics()
    return diagnostics.diagnose(psnr, ssim, lpips, history_stats, training_stats)

