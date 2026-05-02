"""File I/O Utilities."""

import json
import yaml
from pathlib import Path


class FileIO:
    """File input/output utilities."""
    
    @staticmethod
    def load_json(file_path: str) -> dict:
        """Load JSON file."""
        with open(file_path, 'r') as f:
            return json.load(f)
    
    @staticmethod
    def save_json(file_path: str, data: dict):
        """Save JSON file."""
        Path(file_path).parent.mkdir(exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @staticmethod
    def load_yaml(file_path: str) -> dict:
        """Load YAML file."""
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    
    @staticmethod
    def save_yaml(file_path: str, data: dict):
        """Save YAML file."""
        Path(file_path).parent.mkdir(exist_ok=True)
        with open(file_path, 'w') as f:
            yaml.dump(data, f)
