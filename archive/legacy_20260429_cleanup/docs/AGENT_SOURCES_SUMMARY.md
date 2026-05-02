# Agent Sources Summary

## Purpose

This note summarizes the three different sources that currently shape the agent system around the 3D reconstruction project. The goal is to separate:

- current production truth
- future decision-layer design
- external agent-pattern reference

Without that separation, the docs read as if they describe one system, but they are actually describing three different layers of maturity.

## The Three Sources

### 1. Production Layer: `c:\3d-recon-pipeline`

Role:
- Source of truth for the current runnable reconstruction pipeline.
- Handles deterministic execution: preprocess, SfM, 3DGS, export.

What it is good for:
- Understanding what the system actually does today.
- Checking real paths, real outputs, and real scripts.
- Defining the JSON/report contracts that a decision layer should consume.

Current reliability:
- Highest among the three.
- Recently cleaned and aligned around `outputs/`.

Current mainline:
- Phase 0: preprocessing
- Phase 1A: COLMAP SfM
- Phase 1B: 3DGS training
- Phase 2: export / Unity

Important conclusion:
- If there is a conflict between docs and runtime behavior, trust `3d-recon-pipeline` first.

### 2. Decision-Layer Mainline Note: `d:\agent_test\.instructions.md`

Role:
- Current-state note for the executable decision-layer mainline.
- Describes the coordinator flow: validation, routing, recovery advice, reporting.

What it is good for:
- Understanding the split between production and decision layers.
- Understanding the current stage model:
  - PointCloudValidator
  - MapValidator
  - UnityImporter
  - RecoveryAdvisor
  - PhaseReporter
- Preserving the design intent behind the agent system.

What it is not:
- Not the only source of truth.
- Not a substitute for reading the runtime files when debugging.
- Not a guarantee that all older files elsewhere in `agent_test` are still active.

Current reliability:
- High for the current mainline.
- Medium for legacy areas outside the mainline.

Main mismatches with reality:
- Some legacy directories such as `core/`, old docs, and vendored code are still present but are not part of the current Phase-0 mainline.
- The runtime is still code-driven and does not yet execute directly from YAML config.
- The mainline currently handles partial-progress states correctly, but it still depends on production outputs being present.

Important conclusion:
- Treat `.instructions.md` as the current decision-layer guide for the mainline, but continue to trust runtime code and production reports first when they differ.

### 3. External Reference Pattern: `skills-main`

Role:
- Design reference for how an agent or skill system can be organized cleanly.
- Not part of the current reconstruction runtime.

What it is good for:
- Router pattern
- single-responsibility skills
- explicit handoff format
- generated runtime artifacts from source definitions
- validation scripts for structure and metadata

What it is not:
- Not a direct implementation of the 3D reconstruction decision layer.
- Not a drop-in orchestration engine for SfM / 3DGS / Unity.

Current reliability:
- High as an architecture/reference example.
- Not relevant as direct runtime truth for this project.

Most useful ideas we should borrow:
- one front-door router
- one agent per stage
- explicit `Stage` / `Decision` / `Handoff`
- generated or validated contracts instead of ad hoc conventions

Important conclusion:
- Treat `skills-main` as an agent-pattern reference, not as project runtime.

## Recommended Mental Model

Use the three sources like this:

- `3d-recon-pipeline` = current truth
- `agent_test/.instructions.md` = future architecture draft
- `skills-main` = design pattern reference

This is the cleanest way to stop context confusion.

## Current Problems Across the Three Sources

### Problem 1: Truth, blueprint, and reference are mixed together

Right now the project discussion often treats all three as if they describe the same maturity level. They do not.

### Problem 2: The decision layer still contains legacy areas outside the mainline

The mainline now matches `outputs/...`, but parts of `core/`, old docs, and archived ideas still reflect older architectures.

### Problem 3: The decision layer is only partially modernized

`run_phase0.py` and the Phase-0 path now work, but many side files still suggest bigger legacy systems that are not part of the current runtime.

### Problem 4: The reference repo is being mentally treated as implementation

`skills-main` is helpful, but only as a pattern library. It should influence our architecture, not redefine our runtime.

## Recommended Integration Direction

### Production layer should remain responsible for:

- deterministic pipeline execution
- report generation
- standardized outputs

### Decision layer should become responsible for:

- reading production reports
- stage gating
- failure classification
- next-step recommendation
- aggregation into a final summary

### `skills-main` should influence:

- router design
- handoff shape
- agent boundary clarity
- contract validation scripts

## Proposed First Stable Agent Set

Use the following as the first serious decision-layer target:

1. `SfMGate`
   - reads SfM outputs and reports
   - decides whether 3DGS should start

2. `TrainingJudge`
   - reads training outputs and metrics
   - decides pass / extend / retry / inspect SfM

3. `ExportCoordinator`
   - handles export eligibility and downstream integration state

4. `RecoveryAdvisor`
   - classifies failures and blockers
   - explains whether the problem is environment, data, parameters, or pipeline logic

5. `PhaseReporter`
   - aggregates all agent decisions
   - produces human-readable and machine-readable summaries

## Final Takeaway

The project does not have one single broken documentation system. It has three documentation sources with three different jobs:

- one tells the truth about today
- one describes the desired future
- one shows a cleaner design pattern

Once we keep those roles separate, the architecture becomes much easier to reason about and much easier to rebuild cleanly.
