# Phase 2 delivery and acceptance

Phase 2 implements a local library journey from video upload through durable
processing, source-photo observations, immutable calibrated versions and
independently restorable scene packages. Product code delivery and synthetic
workflow coverage are separate from model geometry correctness and human
usability acceptance. Phase 2 is not yet accepted as complete.

## Acceptance status as of 2026-10-11

| Item | Evidence and status |
| --- | --- |
| Upload, review, processing publication, observation and package journey | Automated integration coverage uses real local HTTP, FFmpeg inspection, storage and owned synthetic worker processes. No neural inference is part of these tests. |
| Cancellation, failure, retry and scene isolation | Automated workflow coverage checks queued work, fresh polling, retained failures, distinct retry runs, separate observations and preservation of another Ready scene. |
| Version/default persistence and independent package reopening | Automated workflow coverage closes and restarts ApplicationServer, checks retained names/defaults/exports, then reopens a calibrated package with the linked original unavailable. |
| Full lightweight suite, complete lint/format and JavaScript syntax | October 11 controller run: 489 passed, 1 explicitly opt-in model smoke test skipped, 123.27 seconds. Whole-source/test Ruff passed; 104 Python files passed format checks and 11 first-party JavaScript modules passed syntax checks. Public English scan found no prohibited text. |
| Installed wheel assets and source/benchmark preservation | Offline wheel build passed; isolated unpacked import and 83 byte-identical source files, including 21 static assets, passed without installing dependencies or using the network. Seven historical scene/benchmark SHA-256 checks passed. |
| Independent final review | Four integration findings were fixed; the narrow follow-up review closed the remaining queued-job refresh issue and verified the assertion-preserving test-harness correction. No Critical or Important implementation finding remains in that reviewed scope. |
| Existing scene in a real browser | Executed in isolated Firefox 157.0 headless with WebGL2: named linked import, a 500k-point view, portrait photo selection, red A/B feedback, letterbox rejection, zoom, drag and keyboard nudge. This is partial browser acceptance. |
| Saved photo observation | Executed: Confirm returned focus to the photo-picker control; Add saved a generic observation, then a second source-view observation. The plain summary reported disagreement without forcing calibration. These selections are not a geometry benchmark. |
| Original-phone video upload/review | Executed in the browser: 658,858,445 original bytes transferred, SHA256 verified, oriented HLG still displayed, and Standard/CPU settings saved. Unsupported input was rejected. |
| Processing navigation/refresh | The controller executed a native Start click and browser refresh during the single planned acceptance run. The same one job remained visible and Details retained focus across polling. |
| Single planned real app reconstruction | Completed after one technical retry: CPU, 32 views, 4,873,344 finite points, 32 cameras, Ready publication and restart reopening. The new scene rendered a 500k-point preview in 1.51 seconds in a fresh isolated browser. No physical-accuracy approval is implied. |
| Narrow layout and photo editor | Executed at 390×844 without horizontal overflow: portrait photo, keyboard endpoint placement/nudge, modal focus containment and Escape returning focus. A landscape synthetic fixture also displayed visible A/B picks. |
| Version and portable-package browser journey | Executed on an explicitly synthetic fixture: create a uniformly calibrated version, make default, download full package, restore into a separate application with no linked import roots, and inspect its retained read-only observations and source photo. Fixture references were seeded through the real HTTP API, not created by a human. |
| Two simultaneous scene tabs | Executed on October 11: the historical linked scene retained its saved reference while the new managed scene had none; scene/run/session URLs and selected frames remained separate. The new scene's native photo-picker dialog opened the correct 1920×3414 source and Escape restored focus. No measurement or geometry was changed. |
| Remaining browser journeys | Cancellation, incomplete-transfer recovery and exhaustive error paths retain automated coverage but are not all rendered-browser acceptance. Retry from the interrupted real job was executed through native keyboard input. |
| User completes the journey without developer help | Pending. No human acceptance or screen-reader pass is claimed. Record any action still needing explanation. |

The repeatable synthetic acceptance command is:

```bash
.venv/bin/pytest tests/integration/test_application_workflow.py -q
```

It reuses existing upload, movie, worker, scene and calibration fixtures. It does
not exercise the MapAnything model, frontend rendering, physical accuracy, or
the human's understanding of the workflow.

## Measured responsiveness

These are single-host observations, not guarantees across machines or datasets.

| Engineering target | Executed observation | Limit |
| --- | --- | --- |
| 50 metadata-only cards within 2 seconds | Library listing took 0.032278 seconds with SceneReader.read forbidden. Browser inspection observed all 50 cards on the next animation-frame check by 312 milliseconds after navigation, with a 117-millisecond metadata request and no cloud requests. | These are 50 registrations of the same historical source, not 50 independently reconstructed scenes or a statistical benchmark. |
| Cached 500k-point first display within 10 seconds | Existing 4,873,344-point source rendered a 500,000-point preview in 1.31 seconds; server preview preparation was 0.37 seconds. A later browser opening recorded 1.34 seconds. | Observed in isolated Firefox on this host, not a repeated statistical benchmark. |
| Visible pick feedback on the next rendered frame without a server round trip | Actual portrait photo clicks showed A/B markers on the first next-animation-frame observation; resource count stayed at 20 through selection/nudge. | Limited to the executed photo-editor check. No universal latency guarantee. |
| Bounded video transfer memory | One 658,858,445-byte upload reported 1.002 seconds for transfer and 1.762 seconds for completion/inspection. At 0.5-second sampling, app plus descendants peaked at 316,571,648 bytes summed RSS from a 58,077,184-byte baseline; browser plus descendants peaked at 1,833,144,320 bytes from 1,799,667,712. | App RSS includes FFmpeg inspection and excludes model inference. Shared pages may be counted repeatedly; these are RSS sums, not PSS or whole-host memory. Brief peaks can be missed. |
| App plus processing-worker peak memory | Successful retry sampled at 0.5-second intervals: peak summed RSS 10,555,281,408 bytes (9.83 GiB), peak complete PSS 10,616,138,752 bytes (9.89 GiB). | Sampling began about 20 seconds after launch. RSS/PSS reads were sequential, so maxima need not refer to the same instant. Browser and whole-host memory are excluded; shared RSS pages are counted repeatedly and brief peaks may be missed. GPU peak measurement was unavailable. |
| Endpoint response times | Photo feedback had no HTTP round trip; complete endpoint timing coverage pending. | Do not infer service response guarantees from frontend feedback. |

## Real reconstruction acceptance

One app acceptance uses the original phone MOV already uploaded into the private
library. The input is 64.54 seconds, encoded 3840×2160 and displayed 2160×3840,
with HEVC/HLG inspection and explicit HDR conversion. Standard requests CPU,
up to 32 useful images, automatic budget reduction disabled and zero OOM retries.
The immutable checkpoint revision is documented in [usage](phase2-usage.md).
The successful run used MapAnything 1.1.3, checkpoint
`facebook/map-anything-apache`, revision
`00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`, on CPU. It selected 32 of 129
candidates at timestamps 0, 2, 4, 6, 8, 10, 12, 14, 17, 19, 21, 23, 25, 27,
29, 31, 33, 35, 37, 39, 41, 43, 45, 47, 50, 52, 54, 56, 58, 60, 62 and
64 seconds (99.16% timeline coverage). The saved 1920×3414 images entered the
official preprocessing pipeline as a 294×518 output grid per view.

Total job elapsed time was 1154.58 seconds. Stage durations were inspection
0.10 seconds, selection 210.72 seconds, model loading 18.26 seconds,
reconstruction 918.39 seconds and export 2.13 seconds. Ready publication
retained 4,873,344 finite XYZ points, 32 cameras and 32 depth maps. Output scale
is `estimated_metric`, meters per unit 1.0, with no invented scale confidence.
Raw model confidence mean was 2.544 and median 1.512; these are not accuracy
percentages. `METRIC_SCALE_UNCERTAIN` remains present. Geometry accuracy was
not re-benchmarked or calibrated during this acceptance.

The original attempt was interrupted at export by a session/process shutdown;
it never published Ready and its partial artifacts remain retained. One technical
retry completed successfully with the same frozen settings. No further inference
was launched. Restart reopened the validated result, and a fresh isolated Firefox
browser visibly displayed the resulting point cloud on October 11. The earlier
blank screenshot was not reproduced in that fresh browser; its cause is not
established and no geometry or rendering-code workaround was applied.

This planned run is product acceptance, not a new model comparison. A concrete
implementation/setup failure permits one technical rerun after correction;
disappointing shape does not. Other library/viewer checks reuse existing scenes.
There is no additional inference requirement for using the synthetic tests.

## Concrete limits

The application is local and single-user. One heavy slot supervises processing,
model preparation, calibration and package operations; it is not distributed
processing. Closing the server interrupts work. Retry creates a new run;
inference checkpoints do not resume. Unknown worker ownership blocks new heavy
work until resolved. Storage, transfer, ZIP directory/member and metadata bounds
can reject an otherwise valid input or export. Archive is reversible retention
and does not free space; permanent source deletion is deferred.

Saved versions preserve evidence and reports, while sources stay read-only.
Full packages retain source photos and exclude original videos and model caches.
They are validated before publication, with bounded body reads and central
directory checks before eager ZIP parsing. Downloading only PLY/GLB does not
retain the complete measurement workflow. Linked source availability remains
dependent on its original location or an explicitly located matching source.

Ready means output passed integrity and publication checks. Pipeline/input health,
model confidence, per-reference consistency, physical scale, and use status are
different statements. A single view cannot qualify a scale control; consistency
does not prove physical accuracy. Uniform calibration fixes scale only, not
distorted geometry. Missing mapping, neighborhoods or cameras can leave actions
unavailable rather than inventing evidence. Existing physical-reference evaluation
exposed shape errors; [Phase 1 limits](phase1-delivery.md) still apply.

No alternative backend ranking, mesh/fusion/texturing, multi-video alignment,
automatic endpoints, anisotropic correction, floorplan generation, accounts,
cloud collaboration, or mobile capture application is delivered in this phase.
Human acceptance and the pending checks above must be recorded before closing
Phase 2; UI delivery does not reopen the reconstruction research loop.
