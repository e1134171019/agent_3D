#!/usr/bin/env python
"""Contract-driven Phase-0 runner for the decision layer."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from src.contract_io import read_json


DEFAULT_PRODUCTION_ROOT = Path(r"c:\3d-recon-pipeline\outputs")
DEFAULT_EVENTS_ROOT = DEFAULT_PRODUCTION_ROOT / "agent_events"
DEFAULT_OUTPUT_ROOT = Path(r"d:\agent_test\outputs\phase0")
DEFAULT_DECISIONS_ROOT = DEFAULT_PRODUCTION_ROOT / "agent_decisions"
DEFAULT_UNITY_PROJECT = Path(r"C:\Users\User\Downloads\phase0\Unity\BendViewer")
LATEST_PATTERNS = ("latest_sfm_complete.json", "latest_train_complete.json", "latest_export_complete.json")


class Phase0Runner:
    """Decision-layer runner that consumes production contracts/events."""

    def __init__(
        self,
        production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
        events_root: str | Path = DEFAULT_EVENTS_ROOT,
        output_root: str | Path = DEFAULT_OUTPUT_ROOT,
        decisions_root: str | Path = DEFAULT_DECISIONS_ROOT,
        unity_project: str | Path = DEFAULT_UNITY_PROJECT,
    ):
        self.production_root = Path(production_root)
        self.events_root = Path(events_root)
        self.output_root = Path(output_root)
        self.decisions_root = Path(decisions_root)
        self.unity_project = Path(unity_project)

    @staticmethod
    def _read_json(path: Path) -> dict:
        return read_json(path, expect_object=True)

    def _list_latest_contracts(self) -> list[Path]:
        candidates: list[Path] = []
        for name in LATEST_PATTERNS:
            path = self.events_root / name
            if path.exists():
                candidates.append(path)
        return sorted(candidates, key=lambda p: p.stat().st_mtime_ns)

    def _find_latest_contract(self) -> Path | None:
        candidates = self._list_latest_contracts()
        return candidates[-1] if candidates else None

    def verify_system(self) -> None:
        print("\n" + "=" * 64)
        print("Decision Layer Verification")
        print("=" * 64 + "\n")

        checks: list[bool] = []

        if self.production_root.exists():
            print(f"OK production root: {self.production_root}")
            checks.append(True)
        else:
            print(f"FAIL production root missing: {self.production_root}")
            checks.append(False)

        if self.events_root.exists():
            print(f"OK events root: {self.events_root}")
            latest = self._find_latest_contract()
            if latest:
                print(f"   - latest contract: {latest.name}")
            else:
                print("   - no contract found yet")
            checks.append(True)
        else:
            print(f"WARN events root missing: {self.events_root}")
            checks.append(True)

        self.output_root.mkdir(parents=True, exist_ok=True)
        print(f"OK decision output root ready: {self.output_root}")
        checks.append(True)

        self.decisions_root.mkdir(parents=True, exist_ok=True)
        print(f"OK shared decision root ready: {self.decisions_root}")
        checks.append(True)

        if self.unity_project.exists():
            print(f"OK unity project: {self.unity_project}")
            checks.append(True)
        else:
            print(f"WARN unity project missing, import stage may skip: {self.unity_project}")
            checks.append(True)

        try:
            from agents.phase0 import PointCloudValidator, MapValidator, ProductionParamGate
            from src.coordinator import Phase0Coordinator
            _ = (PointCloudValidator, MapValidator, ProductionParamGate, Phase0Coordinator)
            print("OK phase0 decision modules import successfully")
            checks.append(True)
        except Exception as exc:
            print(f"FAIL phase0 decision modules import failed: {exc}")
            checks.append(False)

        passed = sum(1 for flag in checks if flag)
        total = len(checks)
        print(f"\nVerification: {passed}/{total} passed")
        if all(checks):
            print("OK decision layer ready\n")
        else:
            print("WARN decision layer has blockers\n")

    def execute_single(self, contract_path: str | Path | None = None):
        from src.coordinator import Phase0Coordinator

        contract_file = Path(contract_path) if contract_path else self._find_latest_contract()
        if contract_file is None:
            raise SystemExit(f"找不到 contract。請先確認 {self.events_root} 已有 latest_*.json")
        if not contract_file.exists():
            raise SystemExit(f"contract 不存在: {contract_file}")

        print(f"\n[{datetime.now().isoformat()}] 啟動 Phase-0 contract loop")
        print(f"contract: {contract_file}")

        coordinator = Phase0Coordinator(
            production_path=str(self.production_root),
            events_root=str(self.events_root),
            output_root=str(self.output_root),
            contract_path=str(contract_file),
            unity_project_path=str(self.unity_project),
            decisions_root=str(self.decisions_root),
        )
        result = coordinator.run()
        print(f"[{datetime.now().isoformat()}] Phase-0 完成")
        if result:
            print(f"output: {result.get('output_root', self.output_root)}")
        return result

    def watch_mode(self, poll_seconds: float = 3.0):
        print(f"\n[{datetime.now().isoformat()}] 進入 contract watch mode")
        print(f"watching: {self.events_root}")
        seen: dict[str, int] = {}
        while True:
            try:
                candidates = self._list_latest_contracts()
                if not candidates:
                    time.sleep(poll_seconds)
                    continue

                for contract_file in candidates:
                    mtime_ns = contract_file.stat().st_mtime_ns
                    key = str(contract_file.resolve())
                    if seen.get(key) == mtime_ns:
                        continue
                    seen[key] = mtime_ns
                    try:
                        self.execute_single(contract_path=contract_file)
                    except Exception as exc:
                        print(f"[WARN] contract failed and will not be retried until it changes: {contract_file} ({exc})")
            except KeyboardInterrupt:
                print("\nWatch mode stopped")
                return
            except Exception as exc:
                print(f"[WARN] watch cycle failed: {exc}")
            time.sleep(poll_seconds)


