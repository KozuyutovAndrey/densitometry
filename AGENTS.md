# Project Notes for Codex Agents

## Environment

- This project is managed with `uv`.
- Python version is pinned by `.python-version` and `pyproject.toml`; use Python 3.12+.
- Prefer running project commands through `uv run`, for example:

```bash
uv run python scripts/prepare_artifacts.py
uv run python scripts/prepare_artifacts.py --no-contact-sheets
```

- If the virtual environment is missing or stale, run:

```bash
uv sync
```

## Data and Artifacts

- Source data lives in `data/` as zip archives and should not be manually unpacked unless a task explicitly requires it.
- Generated files go to `artifacts/`.
- `artifacts/` is intentionally ignored by git.
- Main generated files:
  - `artifacts/dicom_index.csv`
  - `artifacts/labels.csv`
  - `artifacts/study_summary.csv`
  - `artifacts/manual_image_review.csv`
  - `artifacts/contact_sheets/`

## Known Sandbox Issue

- In this environment, sandboxed tool calls may fail with:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

- If a read-only or normal project command fails with this error, rerun the same command with `sandbox_permissions="require_escalated"` and a concise justification.
- `apply_patch` can also fail with the same `bwrap` error. If that happens, use a narrowly scoped Python edit through `exec_command` with `require_escalated`.
- Keep such fallback edits small, deterministic, and limited to the requested files. Do not use this as a reason to make broad rewrites.

## Current Data Preparation Workflow

Run:

```bash
uv run python scripts/prepare_artifacts.py
```

This builds the DICOM index, normalized labels, study summary, manual review table, and contact sheets.

For a fast CSV-only check:

```bash
uv run python scripts/prepare_artifacts.py --no-contact-sheets
```

Important conventions:

- Final inference needs one output row per DICOM/image.
- Training should not treat duplicate or derived images from the same study as independent samples.
- Use split by `study_uid`.
- For training/manual geometry, choose a canonical image per `study x region`.
- Empty cells in the Excel markup mean missing/not applicable, not negative labels.
- Hip ROI scale from organizers: `Y = 1.05 mm/px`, `X = 0.6 mm/px`.
