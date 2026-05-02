"""Subprocess Runner Utilities."""

import subprocess
from typing import Tuple


class SubprocessRunner:
    """Utilities for running subprocesses."""
    
    @staticmethod
    def run(command: list, capture_output: bool = True) -> Tuple[int, str, str]:
        """Run a subprocess command."""
        try:
            result = subprocess.run(
                command,
                capture_output=capture_output,
                text=True
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)
    
    @staticmethod
    def run_async(command: list):
        """Run subprocess asynchronously."""
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
