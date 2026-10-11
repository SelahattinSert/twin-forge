# Source-image endpoint selection and plain-language results

## Status and purpose

The user approved the interaction direction on 2026-10-03 and reaffirmed that
all repository-bound content and interface copy must be English. This document
records that direction for review before implementation. No implementation,
commit, push, or new reconstruction is authorized by this document alone.

Make image-based measurement understandable without reading pixel coordinates,
and make evidence and calibration results readable without concealing limits.
This is a focused viewer interaction update, not a new reconstruction method.

## Existing behavior and reported friction

The viewer supports source-image endpoint selection, stores original point and
pixel identities, checks selected observations, and exports separately scaled
scenes. The user has manually completed a two-view qualified reference,
calibration, and direct reopening of the derived scene. Their reported frozen
scalar was 0.927887341. This verifies their reported workflow, not whole-scene
accuracy or a complete browser accessibility/performance audit.

The source-image click handler currently records coordinates without drawing
endpoint markers on the photograph. The photograph is small in the shared card.
Detailed reports expose internal terms that users must interpret to proceed.

## Scope and invariants

- Keep the current offline static viewer, Manrope typography, dark-slate/mint
  design language, and existing backend-independent measurement APIs.
- All UI labels, documentation, comments, and tests are English.
- No new backend, inference, video-upload flow, calibration algorithm, scene
  completion, or reconstruction feature is included.
- Do not alter source images, XYZ, point identities, camera geometry, thresholds,
  stored references, historical benchmarks, or existing source/derived artifacts.
- Image editing changes endpoint selection only; it does not edit the image or
  repair reconstructed geometry. Uniform calibration semantics remain unchanged.
- Remain scene-independent. Do not prefill object types or physical lengths.
- Respect verified pixel provenance, source-only editing, archive read-only
  behavior, and existing stale-response/scene-copy identity protection.
- Do not relax evidence gates or select boundaries using the physical answer.

## Interaction choice

Use an enlarged, accessible image-selection dialog rather than a small inline
image or press-and-drag creation of a measurement. Initial selection uses two
clicks. Dragging adjusts already placed endpoints; it is not the only way to
position or correct them. This avoids confusing image panning with segment
creation and provides an explicit review step.

### Entry and image context

1. The user chooses a source frame in the shared Camera & image card.
2. The image-selection action opens the enlarged photograph with its frame ID
   and timestamp. No object type is required.
3. If selection is unavailable, explain the actual reason: choose a source frame,
   source geometry required, read-only archive, scene loading, or unavailable
   verified image-to-point mapping. Do not enable unsafe picking.
4. The dialog locks its frame/reference/copy context. Normal background controls
   cannot change it while editing; a programmatic context change cancels it.

### Endpoint selection and feedback

- Show the instruction `Select the start point (A).` before the first click and
  `Select the end point (B).` afterward.
- Draw visible A and B markers at the selected image locations, with contrasting
  outlines and explicit labels. Use red markers without relying on color alone.
- Draw a connecting line after both points are placed. Keep markers readable
  when zooming; do not enlarge their stored coordinate values.
- Offer image zoom, pan, and Fit image without stretching or cropping away
  evidence. Panning must not create or move an endpoint.
- Allow an existing marker to be selected and dragged. Also provide non-drag
  endpoint selection and keyboard adjustment so correction does not require
  precise dragging. Keep order explicit: A is the start and B is the end.
- Provide Undo, Clear selection, Confirm selection, and Cancel. Confirmation
  requires two valid in-image positions in the same locked frame context.
- Clicking elsewhere after A/B exist does not silently start another segment;
  select an endpoint to adjust it or explicitly clear the draft.

### Confirmation, cancellation, and persistence

Confirmation transfers the draft A/B positions to the existing observation flow,
closes the dialog, and displays the markers on the shared source photograph.
The user still explicitly identifies physical correspondence and uses Add
observation. Confirmation alone does not POST, qualify a reference, or calibrate.
Adjusting a draft clears its correspondence confirmation.

Cancel and Escape discard unconfirmed edits and preserve the previous confirmed
selection. Frame/reference/copy changes clear incompatible drafts and markers.
Saved reference observations appear only on their matching source frame and
use recorded source pixels or a justified inverse mapping; do not invent image
coordinates for 3D-only records. Archived selections remain read-only.

## Coordinate correctness

Keep selection state in saved-source-raster pixel coordinates, following the
existing convention: integer values denote pixel centers, with rendered image
boundary coordinates converted using the existing half-pixel offset.

The editor's fit, zoom, and pan are display transforms only. Map pointer
coordinates through their inverse before storing source pixels. Derive overlay
locations from the same forward transform. Do not use container bounds as image
bounds when letterboxing exists; ignore clicks outside the actual image.

Use natural image dimensions, retain aspect ratio, and keep the existing verified
source-to-model transform authoritative. Never replace backend XYZ by pinhole
backprojection or infer historical provenance from point counts alone.

Test identical source positions under fit, zoom, pan, viewport resizing, and
portrait/landscape display. Stored source coordinates and resulting endpoint
identities must agree within numerical tolerance. Keep pure image-coordinate
math separate from DOM interaction and existing 3D rendering.

## Plain-language summaries with preserved evidence

Primary summaries answer what happened and what the user can do next. Examples:

- `Choose the same two physical points in another source image.`
- `The selected observations are consistent. This reference can be used to set scale.`
- `The selected endpoints do not line up across images. Review the matching points.`
- `More evidence is needed before this reference can be used to set scale.`
- `Scale set using your reference and 2 source images. Shape accuracy is not verified.`
- `This reference has no evaluated physical-distance comparison.`
- `Saved source observations are read-only in this exported copy.`

Generate summaries from actual server evidence, reasons, calibration records, and
check statuses. Counts must distinguish observations from distinct source views;
repeated clicks in one frame do not become independent views. Translate missing
provenance, incomplete pixel support, and insufficient views into different
actionable explanations, rather than claiming every failure is a bad selection.

Do not call a consistent reference accurate, a calibrated scene verified, or raw
model confidence an accuracy percentage. For conflicting observations, describe
what disagrees without asserting whether user correspondence or reconstruction
is the cause. User review does not automatically make the geometry correct.

Keep full numerical evidence under Technical details: per-view lengths,
spread/sensitivity, thresholds, raw confidence, point IDs, provenance, scalar,
control exclusion, independent check outcomes, and unavailable reasons.
Archive validation failures stay explicit. The physical reference used to set
scale is not counted as an independent accuracy check. Unknown states receive an
honest unavailable summary while retaining their technical status.

## Accessibility and layout

Use a modal with an accessible name, announced instructions, keyboard-reachable
actions, focus containment, Escape cancellation, and focus return to its opener.
Endpoint position/correction must have a keyboard alternative. Interactive
controls use visible focus and at least 44-pixel targets. The photo can occupy
most of the available screen; instructions and confirmation remain reachable on
narrow displays. Preserve reduced-motion behavior and local assets.

These are design requirements, not a claim of WCAG compliance. Rendered browser
and assistive-technology acceptance must be reported separately from unit tests.

## Verification and completion

Before implementation, prepare a focused implementation plan from this reviewed
specification. Add failing tests for coordinate invariance, endpoint lifecycle,
undo/cancel/confirm, context changes, provenance/read-only restrictions, and
plain-language state mapping. Retain existing scalar-once, source-preservation,
reference-generation, and derived-archive regressions.

After implementation, run lightweight tests, lint/format, JavaScript syntax,
offline packaging, protected-hash checks, and read-only HTTP checks. No neural
inference is necessary. Manually verify that the user can see and adjust both
markers, confirm selection, add the same physical endpoints from another view,
read the result, and reopen saved/archived observations. Verify zoom/pan,
keyboard, narrow layout, cancellation, and invalid/unavailable states in a real
browser where available; otherwise report the gap without claiming a pass.

Completion requires clearer interaction with the same geometry, evidence
policy, and data. A more readable report or a successful calibration is not
evidence of improved physical reconstruction accuracy.
