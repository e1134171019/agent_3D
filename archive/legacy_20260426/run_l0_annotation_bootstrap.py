#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run L0 bootstrap annotation agent."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from agents.phase0 import L0AnnotationBootstrapAgent


PIPELINE_ROOT = Path(r"C:\3d-recon-pipeline")
DEFAULT_FRAMES_DIR = PIPELINE_ROOT / "data" / "frames_1600"
DEFAULT_OUTPUT_ROOT = Path(r"D:\agent_test\outputs\l0_annotation_bootstrap")
DEFAULT_DATASET_ROOT = PIPELINE_ROOT / "data" / "annotations"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare bootstrap annotation subset for L0 semantic ROI")
    parser.add_argument("--frames-dir", default=str(DEFAULT_FRAMES_DIR))
    parser.add_argument("--bootstrap-size", type=int, default=24)
    parser.add_argument("--class-name", default="machine")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--dataset-root", default="")
    args = parser.parse_args()

    output_root = Path(args.output_root) / f"bootstrap_{args.bootstrap_size}_{_timestamp()}"
    dataset_root = (
        Path(args.dataset_root)
        if args.dataset_root
        else DEFAULT_DATASET_ROOT / f"bootstrap_{args.bootstrap_size}"
    )

    agent = L0AnnotationBootstrapAgent()
    proposal = agent.propose(
        frames_dir=args.frames_dir,
        bootstrap_size=args.bootstrap_size,
        class_name=args.class_name,
    )
    decision = agent.evaluate()
    result = agent.execute(str(output_root), str(dataset_root))

    print("=" * 72)
    print("L0 ANNOTATION BOOTSTRAP READY")
    print("=" * 72)
    print(f"Frames dir:      {proposal['frames_dir']}")
    print(f"Selected count:  {proposal['bootstrap_size']}")
    print(f"Class:           {proposal['class_name']}")
    print(f"Output root:     {output_root}")
    print(f"Dataset root:    {dataset_root}")
    print(f"Manifest:        {result['manifest_path']}")
    print(f"Rules:           {result['rules_path']}")
    print(f"Approved:        {decision['approved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
