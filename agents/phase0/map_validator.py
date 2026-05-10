"""
MapValidator Agent - 評估 3DGS 地圖品質（改進版本 v2）

職責：
1. 讀取訓練統計數據 (val_step29999.json)
2. 檢查品質指標 (PSNR, SSIM, LPIPS) - 使用自適應閾值
3. 進行根因診斷 (使用規則式診斷引擎)
4. 產生診斷驅動的決策建議

改進：
- ✅ 自適應閾值：根據歷史數據動態調整門檻
- ✅ 診斷驅動：不只是 PASS/FAIL，而是根因分析
- ✅ 歷史感知：讀取過去的決策，判斷趨勢
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict

# 導入改進模塊
from adapters.adaptive_threshold import AdaptiveThreshold
from agents.phase0.map_diagnostics import run_diagnosis, DiagnosisResult
from src.contract_io import read_json


@dataclass
class ValidationMetrics:
    psnr: float
    ssim: float
    lpips: float
    
    # 決策門檻（預設值，會被自適應閾值覆蓋）
    PASS_PSNR = 20.0
    PASS_SSIM = 0.80
    PASS_LPIPS = 0.15


class MapValidator:
    def __init__(self, config=None, log_path: str = "outputs/phase0/phase0_decisions.log"):
        """
        初始化
        
        Args:
            config: 配置字典（可選）
            log_path: 決策日誌路徑，用於讀取歷史數據
        """
        self.config = config or {}
        self.metrics = None
        self.proposal = None
        self.decision = None
        self.diagnosis = None
        
        # 初始化自適應閾值管理器
        self.adaptive_threshold = AdaptiveThreshold(log_path, window=10)
        
    def propose(self, stats_json_path: str) -> dict:
        r"""
        Proposal 階段：讀取統計數據，進行診斷，產生決策建議
        
        改進：
        - 不只讀取指標值，還要進行根因診斷
        - 診斷會考慮歷史趨勢和當前訓練狀態
        
        Args:
            stats_json_path: c:\3d-recon-pipeline\outputs\3DGS_models\stats\val_step29999.json
        
        Returns:
            dict: {
                "proposal_id": "VAL-001",
                "proposal_text": "...",
                "metrics": {...},
                "diagnosis": {...},  # 新增：診斷結果
                "diagnosis_action": "approve|retrain|investigate"  # 新增：診斷建議
            }
        """
        try:
            stats = read_json(stats_json_path, expect_object=True)
            
            self.metrics = ValidationMetrics(
                psnr=stats.get('psnr', 0),
                ssim=stats.get('ssim', 0),
                lpips=stats.get('lpips', 0)
            )
            
            # 執行根因診斷
            history_stats = self._analyze_history()
            training_stats = self._analyze_training(stats)
            
            # 調用規則式診斷引擎
            self.diagnosis = run_diagnosis(
                psnr=self.metrics.psnr,
                ssim=self.metrics.ssim,
                lpips=self.metrics.lpips,
                history_stats=history_stats,
                training_stats=training_stats,
                thresholds={
                    "psnr": ValidationMetrics.PASS_PSNR,
                    "ssim": ValidationMetrics.PASS_SSIM,
                    "lpips": ValidationMetrics.PASS_LPIPS,
                },
            )
            
            self.proposal = {
                "proposal_id": "VAL-001",
                "timestamp": datetime.now().isoformat(),
                "proposal_text": f"檢驗地圖品質：PSNR={self.metrics.psnr:.2f}, SSIM={self.metrics.ssim:.3f}, LPIPS={self.metrics.lpips:.3f}。診斷：{self.diagnosis.reason}",
                "metrics": asdict(self.metrics),
                "diagnosis": {
                    "diagnosis_name": self.diagnosis.diagnosis,
                    "confidence": self.diagnosis.confidence,
                    "reason": self.diagnosis.reason,
                    "recommended_action": self.diagnosis.action,
                    "details": self.diagnosis.details
                },
                "diagnosis_action": self.diagnosis.action  # 簡化了供 evaluate 使用
            }
            
            return self.proposal
        
        except Exception as e:
            self.proposal = {
                "proposal_id": "VAL-001",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "status": "failed"
            }
            return self.proposal
    
    def _analyze_history(self) -> Optional[Dict]:
        """從歷史日誌中分析過去的決策和趨勢"""
        try:
            recent_psnr = self.adaptive_threshold._extract_recent_successful_metrics("psnr")
            recent_ssim = self.adaptive_threshold._extract_recent_successful_metrics("ssim")
            recent_lpips = self.adaptive_threshold._extract_recent_successful_metrics("lpips")
            
            if not any(len(values) >= 2 for values in (recent_psnr, recent_ssim, recent_lpips)):
                return None
            
            def _avg(values):
                return sum(values) / len(values) if values else 0

            return {
                "total_runs": len(self.adaptive_threshold.history),
                "avg_psnr": _avg(recent_psnr),
                "psnr_trend": self.adaptive_threshold.get_trend("psnr") or "unknown",
                "avg_ssim": _avg(recent_ssim),
                "avg_lpips": _avg(recent_lpips),
                "ssim_trend": self.adaptive_threshold.get_trend("ssim") or "unknown",
                "lpips_trend": self.adaptive_threshold.get_trend("lpips") or "unknown",
            }
        except Exception:
            return None
    
    def _analyze_training(self, stats: dict) -> Optional[Dict]:
        """從統計數據中分析訓練進度"""
        try:
            # 假設 stats 包含訓練相關信息
            return {
                "steps_completed": stats.get("iteration", 0),
                "max_steps": 30000
            }
        except Exception:
            return None
    
    def evaluate(self) -> dict:
        """
        Evaluate 階段：Coordinator 檢查決策規則（改進版本）
        
        改進：
        - 使用自適應閾值而非硬編碼值
        - 根據診斷建議調整決策
        
        Returns:
            dict: {
                "pass_psnr": True/False,
                "pass_ssim": True/False,
                "pass_lpips": True/False,
                "overall_pass": True/False,
                "adaptive_thresholds": {...},
                "rules": [...]
            }
        """
        if not self.metrics:
            return {"overall_pass": False, "error": "metrics not set"}
        
        # 計算自適應閾值
        adaptive_psnr = self.adaptive_threshold.get_threshold(
            "psnr", 
            base=ValidationMetrics.PASS_PSNR,
            min_threshold=ValidationMetrics.PASS_PSNR * 0.7,  # 最多降低 30%
            max_threshold=ValidationMetrics.PASS_PSNR * 1.3
        )
        
        adaptive_ssim = self.adaptive_threshold.get_threshold(
            "ssim",
            base=ValidationMetrics.PASS_SSIM,
            min_threshold=ValidationMetrics.PASS_SSIM * 0.85,
            max_threshold=ValidationMetrics.PASS_SSIM * 1.0
        )
        
        adaptive_lpips = self.adaptive_threshold.get_threshold(
            "lpips",
            base=ValidationMetrics.PASS_LPIPS,
            min_threshold=ValidationMetrics.PASS_LPIPS * 0.8,
            max_threshold=ValidationMetrics.PASS_LPIPS * 1.5
        )
        
        # 根據自適應閾值評估
        rules = [
            {
                "type": "psnr_threshold",
                "value": self.metrics.psnr,
                "threshold": adaptive_psnr,
                "threshold_type": "adaptive",
                "pass": self.metrics.psnr > adaptive_psnr
            },
            {
                "type": "ssim_threshold",
                "value": self.metrics.ssim,
                "threshold": adaptive_ssim,
                "threshold_type": "adaptive",
                "pass": self.metrics.ssim > adaptive_ssim
            },
            {
                "type": "lpips_threshold",
                "value": self.metrics.lpips,
                "threshold": adaptive_lpips,
                "threshold_type": "adaptive",
                "pass": self.metrics.lpips < adaptive_lpips
            }
        ]
        
        # 根據診斷調整最終決策
        basic_pass = all(rule["pass"] for rule in rules)
        
        diagnosis_override_applied = False
        diagnosis_confidence = self.diagnosis.confidence if self.diagnosis else 0.0
        strong_diagnosis = diagnosis_confidence >= 0.80

        # 只有高信心診斷才能覆寫基本品質規則，避免弱診斷永久鎖住 train gate。
        if self.diagnosis and self.diagnosis.action == "retrain" and strong_diagnosis:
            overall_pass = False
            decision_note = f"診斷建議：{self.diagnosis.reason} → 需要重新訓練"
            diagnosis_override_applied = True
        elif self.diagnosis and self.diagnosis.action == "investigate" and strong_diagnosis:
            overall_pass = basic_pass
            decision_note = f"診斷建議：{self.diagnosis.reason} → 需要手動檢查"
            diagnosis_override_applied = not basic_pass
        else:
            overall_pass = basic_pass
            decision_note = "根據自適應閾值進行評估"
        
        quality_score = self.adaptive_threshold.get_quality_score(
            self.metrics.psnr,
            self.metrics.ssim,
            self.metrics.lpips
        )
        
        self.decision = {
            "evaluation_timestamp": datetime.now().isoformat(),
            "rules": rules,
            "overall_pass": overall_pass,
            "quality_score": quality_score,
            "diagnosis_override_applied": diagnosis_override_applied,
            "adaptive_thresholds": {
                "psnr": adaptive_psnr,
                "ssim": adaptive_ssim,
                "lpips": adaptive_lpips
            },
            "decision_note": decision_note
        }
        
        return self.decision
    
    def execute(self, output_path: str) -> dict:
        """
        Execute 階段：輸出驗證報告（改進版本）
        
        改進：
        - 包含診斷結果
        - 包含自適應閾值用於審計
        
        Args:
            output_path: outputs/phase0/validation_report.json
        
        Returns:
            dict: 執行結果
        """
        if not self.decision:
            return {"status": "error", "message": "decision not evaluated"}
        
        try:
            report = {
                "timestamp": datetime.now().isoformat(),
                "psnr": self.metrics.psnr,
                "ssim": self.metrics.ssim,
                "lpips": self.metrics.lpips,
                "quality_score": self.decision.get("quality_score"),
                "overall_pass": self.decision["overall_pass"],
                "decision_rules": self.decision["rules"],
                "adaptive_thresholds": self.decision.get("adaptive_thresholds", {}),
                "decision_note": self.decision.get("decision_note", ""),
                "diagnosis": {
                    "diagnosis_name": self.diagnosis.diagnosis if self.diagnosis else "unknown",
                    "confidence": self.diagnosis.confidence if self.diagnosis else 0,
                    "recommended_action": self.diagnosis.action if self.diagnosis else "investigate",
                    "reason": self.diagnosis.reason if self.diagnosis else "未進行診斷",
                    "details": self.diagnosis.details if self.diagnosis else {}
                }
            }
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            return {
                "status": "success",
                "path": output_path,
                "overall_pass": self.decision["overall_pass"]
            }
        
        except Exception as e:
            return {"status": "error", "message": str(e)}
