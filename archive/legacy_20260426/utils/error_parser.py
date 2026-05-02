"""Error Parser - Parses and categorizes errors."""

import re


class ErrorParser:
    """Parser for analyzing error messages."""
    
    ERROR_PATTERNS = {
        "cuda": r"CUDA|cuda|kernel",
        "memory": r"memory|out of memory|OOM",
        "import": r"ImportError|ModuleNotFoundError",
        "build": r"build failed|compilation error|undefined reference",
        "torch": r"PyTorch|torch|Tensor"
    }
    
    @staticmethod
    def categorize(error_msg: str) -> str:
        """Categorize error message."""
        for category, pattern in ErrorParser.ERROR_PATTERNS.items():
            if re.search(pattern, error_msg, re.IGNORECASE):
                return category
        return "unknown"
    
    @staticmethod
    def suggest_fix(error_msg: str) -> str:
        """Suggest a fix for error."""
        category = ErrorParser.categorize(error_msg)
        
        suggestions = {
            "cuda": "Check CUDA installation and GPU compatibility",
            "memory": "Reduce batch size or model size",
            "import": "Install missing dependencies",
            "build": "Check compilation flags and dependencies",
            "torch": "Update PyTorch to compatible version"
        }
        
        return suggestions.get(category, "Check error logs for details")
