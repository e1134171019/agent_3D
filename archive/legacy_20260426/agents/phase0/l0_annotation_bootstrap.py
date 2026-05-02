"""L0 annotation bootstrap agent.

Generate a small, deterministic bootstrap set for YOLO segmentation annotation.
This agent does not auto-label. It prepares:
  - selected images
  - YOLO-seg dataset skeleton
  - manifest and annotation rules
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class BootstrapSelection:
    image_name: str
    source_path: str
    order_index: int
    bucket_index: int


class L0AnnotationBootstrapAgent:
    """Prepare a bootstrap annotation subset for L0 semantic ROI exploration."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.proposal: dict[str, Any] | None = None
        self.decision: dict[str, Any] | None = None
        self.selection: list[BootstrapSelection] = []

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def _list_images(frames_dir: Path) -> list[Path]:
        images = sorted(frames_dir.glob("*.jpg"))
        if not images:
            images = sorted(frames_dir.glob("*.png"))
        return images

    @staticmethod
    def _pick_evenly_spaced(images: list[Path], bootstrap_size: int) -> list[BootstrapSelection]:
        if bootstrap_size <= 0:
            raise ValueError("bootstrap_size must be > 0")
        if not images:
            raise ValueError("no images found")

        if bootstrap_size >= len(images):
            indices = list(range(len(images)))
        else:
            indices = []
            for bucket_idx in range(bootstrap_size):
                start = int(bucket_idx * len(images) / bootstrap_size)
                end = int((bucket_idx + 1) * len(images) / bootstrap_size)
                center = (start + max(start, end - 1)) // 2
                indices.append(center)

        picked: list[BootstrapSelection] = []
        for bucket_idx, idx in enumerate(indices):
            image = images[idx]
            picked.append(
                BootstrapSelection(
                    image_name=image.name,
                    source_path=str(image),
                    order_index=idx,
                    bucket_index=bucket_idx,
                )
            )
        return picked

    def propose(
        self,
        frames_dir: str,
        bootstrap_size: int = 24,
        class_name: str = "machine",
    ) -> dict[str, Any]:
        frames_path = Path(frames_dir)
        images = self._list_images(frames_path)
        self.selection = self._pick_evenly_spaced(images, bootstrap_size)

        self.proposal = {
            "proposal_id": "L0AB-001",
            "timestamp": datetime.now().isoformat(),
            "proposal_text": "建立 L0 semantic ROI 的 bootstrap 標註子集",
            "frames_dir": str(frames_path),
            "bootstrap_size": bootstrap_size,
            "class_name": class_name,
            "total_images": len(images),
            "selected_images": [item.image_name for item in self.selection],
            "selection_strategy": "evenly_spaced_stratified_sampling",
            "annotation_policy": {
                "num_classes": 1,
                "class_name": class_name,
                "annotation_style": "coarse_segmentation_or_polygon",
                "exclude_objects": ["fan", "tool", "basket", "screen", "table", "cable", "glove"],
            },
        }
        return self.proposal

    def evaluate(self) -> dict[str, Any]:
        count = len(self.selection)
        approved = 20 <= count <= 50
        self.decision = {
            "evaluation_timestamp": datetime.now().isoformat(),
            "approved": approved,
            "reason": "bootstrap_set_in_expected_range" if approved else "bootstrap_size_out_of_range",
            "selected_count": count,
        }
        return self.decision

    def execute(self, output_dir: str, pipeline_dataset_root: str) -> dict[str, Any]:
        if self.proposal is None or self.decision is None:
            raise RuntimeError("propose() and evaluate() must be called before execute()")

        output_path = Path(output_dir)
        dataset_root = Path(pipeline_dataset_root)
        images_dir = dataset_root / "images"
        labels_dir = dataset_root / "labels"

        output_path.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)

        for item in self.selection:
            src = Path(item.source_path)
            dst = images_dir / item.image_name
            shutil.copy2(src, dst)

            label_stub = labels_dir / f"{src.stem}.txt"
            if not label_stub.exists():
                label_stub.write_text("", encoding="utf-8")

        dataset_yaml = dataset_root / "dataset.yaml"
        dataset_yaml.write_text(
            "\n".join(
                [
                    f"path: {dataset_root.as_posix()}",
                    "train: images",
                    "val: images",
                    "names:",
                    f"  0: {self.proposal['class_name']}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        manifest_path = output_path / "bootstrap_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "timestamp": datetime.now().isoformat(),
                    "status": "success",
                    "proposal": self.proposal,
                    "decision": self.decision,
                    "dataset_root": str(dataset_root),
                    "images_dir": str(images_dir),
                    "labels_dir": str(labels_dir),
                    "dataset_yaml": str(dataset_yaml),
                    "selection": [item.__dict__ for item in self.selection],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        rules_path = output_path / "ANNOTATION_RULES.md"
        rules_path.write_text(
            "\n".join(
                [
                    "# L0 Bootstrap Annotation Rules",
                    "",
                    "## Goal",
                    "Prepare a first-round YOLO segmentation bootstrap set for semantic ROI experiments.",
                    "",
                    "## Scope",
                    f"- Class count: 1",
                    f"- Class name: `{self.proposal['class_name']}`",
                    f"- Image count: {len(self.selection)}",
                    "",
                    "## Annotation Rules",
                    "- Use coarse segmentation or coarse polygon only.",
                    "- Cover the main machine body as consistently as possible.",
                    "- Keep obvious background out when easy to exclude.",
                    "- Treat fan, basket, tools, cables, table, glove, and monitors as background.",
                    "- Do not spend time on pixel-perfect boundaries in the first round.",
                    "",
                    "## Expected Outcome",
                    "- A consistent bootstrap set for fine-tuning YOLO11-seg or validating semantic ROI feasibility.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        selected_list_path = output_path / "selected_images.txt"
        selected_list_path.write_text(
            "\n".join(item.image_name for item in self.selection) + "\n",
            encoding="utf-8",
        )

        return {
            "status": "success",
            "manifest_path": str(manifest_path),
            "rules_path": str(rules_path),
            "dataset_root": str(dataset_root),
            "selected_count": len(self.selection),
        }
