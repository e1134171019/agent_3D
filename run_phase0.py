#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase-0 decision entrypoint driven by production contracts/events."""

import argparse
from src.phase0_runner import Phase0Runner


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "pass", "useful"}:
        return True
    if normalized in {"false", "0", "no", "n", "fail", "useless"}:
        return False
    if normalized in {"none", "null", "unknown", "skip"}:
        return None
    raise argparse.ArgumentTypeError(f"invalid bool label: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase-0: consume production contracts and emit decision reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_phase0.py --verify
  python run_phase0.py --contract C:\\3d-recon-pipeline\\outputs\\agent_events\\latest_train_complete.json
  python run_phase0.py --watch
        """,
    )
    parser.add_argument("--verify", action="store_true", help="Verify decision-layer configuration")
    parser.add_argument("--watch", action="store_true", help="Watch production agent_events and rerun on changes")
    parser.add_argument("--contract", type=str, default="", help="Stage contract / latest event json path")
    parser.add_argument("--production-root", type=str, default=r"c:\3d-recon-pipeline\outputs", help="Production outputs root")
    parser.add_argument("--events-root", type=str, default=r"c:\3d-recon-pipeline\outputs\agent_events", help="Production contract/event root")
    parser.add_argument("--output-root", type=str, default=r"d:\agent_test\outputs\phase0", help="Decision-layer output root")
    parser.add_argument("--decisions-root", type=str, default=r"c:\3d-recon-pipeline\outputs\agent_decisions", help="Shared decision root written back to production layer")
    parser.add_argument("--unity-project", type=str, default=r"C:\Users\User\Downloads\phase0\Unity\BendViewer", help="Unity project path used by import stage")
    parser.add_argument("--poll-seconds", type=float, default=3.0, help="Polling interval for watch mode")
    parser.add_argument("--label-feedback", type=str, default="", help="Outcome feedback JSON to label")
    parser.add_argument("--decision-useful", type=_parse_optional_bool, default=None, help="Whether the decision was useful")
    parser.add_argument("--metrics-improved", type=_parse_optional_bool, default=None, help="Whether metrics improved after the decision")
    parser.add_argument("--problem-layer-correct", type=_parse_optional_bool, default=None, help="Whether the selected problem layer was correct")
    parser.add_argument("--human-override", type=_parse_optional_bool, default=None, help="Whether human override was needed")
    parser.add_argument("--wasted-run", type=_parse_optional_bool, default=None, help="Whether this decision caused a wasted run")
    parser.add_argument("--repeated-problem", type=_parse_optional_bool, default=None, help="Whether this repeated a known problem")
    parser.add_argument("--critical-bad-release", type=_parse_optional_bool, default=None, help="Whether it caused a critical bad release")
    parser.add_argument("--label-source", type=str, default="human", help="Outcome label source")
    parser.add_argument("--label-note", type=str, default="", help="Short human note for the label")
    args = parser.parse_args()

    runner = Phase0Runner(
        production_root=args.production_root,
        events_root=args.events_root,
        output_root=args.output_root,
        decisions_root=args.decisions_root,
        unity_project=args.unity_project,
    )

    if args.label_feedback:
        from pathlib import Path
        from src.outcome_feedback import OutcomeFeedbackHistory

        feedback_path = Path(args.label_feedback)
        if len(feedback_path.parents) < 3:
            raise SystemExit(f"feedback path is too shallow: {feedback_path}")
        audit_root = feedback_path.parents[2]
        history = OutcomeFeedbackHistory(audit_root)
        updated = history.apply_label(
            feedback_path,
            decision_useful=args.decision_useful,
            metrics_improved=args.metrics_improved,
            problem_layer_correct=args.problem_layer_correct,
            human_override=args.human_override,
            wasted_run=args.wasted_run,
            repeated_problem=args.repeated_problem,
            critical_bad_release=args.critical_bad_release,
            label_source=args.label_source,
            label_note=args.label_note,
        )
        curve_path = feedback_path.parent / "learning_curve.json"
        curve = history.write_learning_curve(curve_path)
        print(f"OK outcome label updated: {feedback_path}")
        print(f"decision_useful: {updated.get('decision_useful')}")
        print(f"learning_curve: {curve_path}")
        print(f"total_decisions: {curve.get('total_decisions')}")
        return 0

    if args.verify:
        runner.verify_system()
        return 0

    if args.watch:
        runner.watch_mode(poll_seconds=args.poll_seconds)
        return 0

    runner.execute_single(contract_path=args.contract or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


