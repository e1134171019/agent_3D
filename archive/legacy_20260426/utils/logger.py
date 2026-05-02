"""Logging Utilities."""

import logging
from pathlib import Path


class LoggerFactory:
    """Factory for creating loggers."""
    
    @staticmethod
    def create_logger(name: str, log_file: str = None):
        """Create a logger instance."""
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(name)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler if specified
        if log_file:
            Path(log_file).parent.mkdir(exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
