# room2-video2 Local-Pair Camera Control — Experiment Design

## Purpose

Test one explanation for the unstable independent RGB camera solution: verified image pairs separated by more than three seconds may impose misleading long-range constraints. This experiment tests that hypothesis; it does not assume it is true. The primary scene remains `room2-video2`; `room2` is not a gate for this experiment.

## Frozen baseline

The completed 65-image camera-bridge experiment is immutable. It registered all original 32 target images and 33 auxiliary images, but failed the predeclared camera gate: full held-out target reprojection P90 was 4.124 px (limit 4 px); both fixed subset controls exceeded the center and rotation stability limits. Its 374 verified pair edges include 202 with timestamp separation greater than three seconds. The remaining 172 local edges connect all 65 images in one graph. This connectivity is necessary but not sufficient for a valid sparse reconstruction.

The source video, original 32 target JPEGs and order, 33 approved auxiliary JPEGs, ALIKED–LightGlue features, two-view verification, camera model, mapper options, physical benchmark references, historical MapAnything results, and the existing camera gate remain unchanged. Source and experiment input hashes must be checked before and after. The physical measurements and MapAnything geometry must not enter the RGB camera solution.

## Alternatives considered

1. **Recommended: local-pair graph control.** Use a new copy of the verified 65-image COLMAP database. Remove only `two_view_geometries` rows whose image timestamps differ by more than three seconds. Keep keypoints, image records, cameras, rigs, frames, and every retained geometry row unchanged. This isolates the suspected long-range graph constraints without selecting different source pixels or tuning the mapper.
2. Change to `SIMPLE_PINHOLE`. This tests lens-model flexibility, but the observed subset focal changes are under 1%, while camera orientation differences can approach 90–180°. It is less directly motivated by the current evidence and would change a different variable.
3. Extract yet more video frames. This changes observation density and feature matching at once, although the bridge already registered all 65 images. It is not the first controlled test.

## Experiment procedure

Before any mapping, write an isolated, gitignored protocol manifest naming source hashes, fixed input image names and ordering, the exact three-second temporal rule, expected 172 retained and 202 excluded verified pairs, three fixed mapping arms, unchanged software settings and gate, and the stop rule. Verify that the retained match graph connects all 65 images. Never edit the completed bridge database in place.

Run one full sparse COLMAP mapping and bundle adjustment on the 65 images. Then run the *same* two fixed controls as before: `drop_mod0` and `drop_mod2`, each retaining 24 original target images and its predeclared subset of auxiliary images. Each control reads a separate copy of the locally filtered database. No adaptive seed, match threshold, camera-model, frame selection, or gate retuning is allowed after seeing results.

Compute the same registered-camera coverage, sparse point and track statistics, triangulation angles, RGB door/floor/ceiling support, target-only held-out reprojection error, and target-camera center/rotation/focal subset-stability metrics as the completed bridge experiment. Apply **unchanged** `output/camera-conditioning-20260927/protocol.json:camera_solution_gate`: all 32 targets in one component; median track length ≥3; median maximum triangulation angle ≥3°; at least 15 unique supported door tracks; target held-out P90 ≤4 px; at least 16 common target cameras per control; center residual P90 / camera diameter ≤0.05; rotation difference P90 ≤5°; relative focal change ≤0.10. An attractive training residual or graph connectivity cannot override a failed gate.

## Interpretation and stop rule

If either control or the full solution fails any gate, report `camera_solution_insufficient`; do not run MapAnything M1/M2 or DA3, do not loosen thresholds, and do not infer that camera conditioning is ineffective. If the gate passes, use the already-approved next stage: fresh MapAnything M0/M1/M2 on the **original same 32 target JPEGs only**, same checkpoint/revision, preprocessing, inference resolution and precision, preserving raw provenance. Relative COLMAP poses must not be labeled metric. Apply unchanged physical benchmarks only after inference. If 32-view neural inference is infeasible, report that explicitly; do not silently reduce the view count.

All new products live in a separate gitignored experimental directory. No TwinForge production engine code, old reconstruction, old benchmark, or protected artifact is modified. This protocol is a new controlled experiment, not a retrospective pass of the failed bridge gate.

## Validation and failure handling

Unit tests must prove that a copied database retains all original non-geometry rows byte-equivalently, keeps exactly the timestamp-eligible verified geometries, rejects missing/duplicate image timestamps, and leaves the source database hash unchanged. A read-only graph check must confirm 65 connected images before mapping. If any integrity or setup check fails, preserve the failed attempt and stop before the next arm. After mapping, recheck protected hashes and run the experiment tests. The final report must include gate outcomes, stage runtimes and peak RAM/VRAM, changed-variable audit, and the absence or presence of M0/M1/M2 results.
