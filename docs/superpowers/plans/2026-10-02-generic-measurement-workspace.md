# Generic Measurement Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a genuinely redesigned, scene-independent measurement interface without changing reconstruction geometry.

**Architecture:** Keep the local static Three.js viewer and existing measurement APIs. Separate workflow presentation and eligibility state from 3D rendering through a small pure JavaScript module. Preserve historical scene records as scene-bound data.

**Tech Stack:** Native HTML, CSS, JavaScript modules, vendored Three.js, vendored Manrope, Python HTTP server, pytest, Node.js.

## Global Constraints

- All GitHub-bound source, documentation, tests, comments, and UI copy must be English.
- No reconstruction, backend, benchmark, calibration algorithm, original artifact, or historical measurement is changed.
- No inference, Git mutation, commit, push, or PR is authorized.
- Original XYZ, point indices, frame and pixel provenance, camera axes, scene-copy request generation guards, archive read-only behavior, uniform-scale semantics, and evidence qualifications remain unchanged.
- No scene-specific reference identifier or physical length is prefilled in generic UI controls.
- Calibration is optional and requires an active qualified reference and explicit finite positive length; model confidence is not metric accuracy.
- Keep the UI offline and dependency-light; preserve vendor licenses.
- Do not claim browser visual acceptance or complete accessibility without actual evidence.

### Task 1: Redesign the viewer and generic reference workflow

**Files:**

- Modify: `src/twinforge/viewer/static/index.html`, `styles.css`, `app.js`.
- Create: `src/twinforge/viewer/static/workspace-ui.js` for presentation state and eligibility helpers; keep geometry rendering in `app.js`.
- Modify: `src/twinforge/viewer/server.py` only for explicit new static asset routes.
- Create: `src/twinforge/viewer/static/vendor/manrope-latin-wght-normal.woff2` and `MANROPE-LICENSE` from the prepared pinned font package.
- Test: `tests/unit/test_viewer_measurement_ui.py`, new `tests/unit/test_viewer_workspace_ui.py`, and `tests/integration/test_viewer.py`.
- Update: `docs/phase1-usage.md`, `docs/dependencies.md` and add `docs/phase1-ui-refresh.md`.

**Interfaces:** Existing `/api/scene`, `/api/measurements`, measurement observation POST, `/api/calibration`, `/api/check-report`, and `/api/archive` remain unchanged. Read `app.js` and the fixture tests before editing. New UI helpers consume these existing structures; inspect actual evidence fields rather than inventing qualification flags. New module and font routes must be explicit in `STATIC_FILES` and included by existing wheel package-data patterns.

- [x] Step 1: Add failing regression tests before production edits. Parse actual HTML to assert blank `reference-id`, no physical-length default, Segment default, labeled Inspect/Measure/Calibrate navigation, and separate saved-scene/archive sections. Test production eligibility helpers for blank, zero, negative, NaN, infinity, qualified source reference, unqualified reference, read-only archive, and derived copy. Test reference/copy transitions clear physical input and reject stale measurement eligibility. Capture the failing command and output.

```bash
.venv/bin/pytest tests/unit/test_viewer_workspace_ui.py -q
```

- [x] Step 2: Implement a substantial redesign: branded compact header, prominent 3D viewport, professional dark-slate palette with restrained mint accent, locally hosted Manrope with system fallback, body text at least 14px, consistent spacing, and clear heading hierarchy. Provide Inspect / Measure / Calibrate step buttons with selected state and keyboard access; calibration is visibly optional. Move low-level hashes, pixel diagnostics, archive JSON, raw confidence, and visibility masking behind native details elements. Do not remove functions or numerical evidence. Make empty, loading, success, and error states understandable. Retain the viewport IDs and source camera/image interactions, including exact pixel mapping.

```css
@font-face {
  font-family: "Manrope";
  src: url("/vendor/manrope-latin-wght-normal.woff2") format("woff2");
  font-weight: 200 800;
  font-style: normal;
  font-display: swap;
}
```

- [x] Step 3: Start a new measurement with no object-specific defaults. Preserve reopening saved scene references and read-only archive records. Explain identifier restrictions and use neutral examples. Add a clear new-reference action so users can leave a reopened reference without contaminating the next measurement. Calibration eligibility and action must use the same helper, not duplicated divergent rules. Clear physical length on reference selection/change, new-reference action, archive selection, and scene-copy switch; never copy archived/control length into the entry form. Validate finite positive length before submitting. Keep existing server validation and qualified consistency requirements authoritative. Preserve request-generation protections and endpoint scalar-once behavior.

- [x] Step 4: Run focused tests, then update documentation with the real workflow, scene-bound saved data distinction, optional calibration limitations, font version/license/hash, and browser-test limitations. Add HTTP assertions for module/font/license and unknown paths; verify `font/woff2`. Use 44px controls, visible keyboard focus, non-color status text, `aria-live` for interaction status, reduced motion, and responsive layout that fits 320px without control overflow.

```bash
.venv/bin/pytest tests/unit/test_viewer_measurement_ui.py tests/unit/test_viewer_workspace_ui.py -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
node --check src/twinforge/viewer/static/app.js
node --check src/twinforge/viewer/static/workspace-ui.js
```

- [x] Step 5: Self-review, write `output/phase1/ui-refresh/task-1-report.md` with RED/GREEN commands and outputs, changed files, and honest limitations. Do not commit. Request independent task review, address important findings, then broad review.

## Controller acceptance

- [x] Run all lightweight tests with model smoke disabled; HTTP tests may require explicit socket permission.
- [x] Build a wheel offline and verify module, font, and license are packaged, with no private scene data.
- [x] Recheck protected historical hashes and run existing real-artifact read-only HTTP checks.
- [x] Attempt browser visual acceptance using the permitted UI surface; if unavailable, report this explicitly.
- [x] Report the changes and exact verification evidence without claiming improved reconstruction accuracy.

## Completion evidence

The final lightweight suite returned **283 passed, 1 opt-in model smoke skipped**.
Focused calibration/UI tests, Ruff, formatting, JavaScript syntax, offline wheel
asset comparisons, protected hashes, and four real-scene read-only HTTP checks
passed. Independent task and broad reviews approved with all findings resolved.
Rendered browser acceptance was attempted but unavailable through the permitted
surface; the checked attempt above does not mean visual acceptance passed.
See `docs/phase1-ui-refresh.md` for the workflow and remaining validation limit.
