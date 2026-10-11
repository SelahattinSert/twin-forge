# Scene-first application refresh

## Scope

This update improves navigation, scene discovery, opening feedback and visual
hierarchy. It does not change reconstruction, point coordinates, observation
qualification, calibration, benchmark results or saved reconstruction artifacts.
All application copy remains English. No new UI dependency or remote asset is
required.

## Research and design rationale

The research covered public product pages and official workflow documentation,
not authenticated customer accounts. Product features and advertised accuracy
are not evidence for TwinForge geometry quality.

- [SkyeBrowse's official viewer tutorial](https://www.skyebrowse.com/news/posts/tutorial-3d-model-viewer)
  describes a model-card opening action and separates analysis tools from
  deliverables. TwinForge adopts the clear card-to-workspace hierarchy, not its
  branding, domain-specific tools or scene-generation features.
- [SkyeBrowse's viewer redesign notes](https://www.skyebrowse.com/news/posts/the-biggest-makeover-in-skyebrowse-history)
  emphasize onboarding and contextual help. TwinForge makes the next action
  explicit in empty, processing and unavailable-source states.
- [Polycam's spatial capture overview](https://poly.cam/spatial-capture) and
  [official existing-media workflow](https://learn.poly.cam/hc/en-us/articles/30549121659412-How-to-Create-Photogrammetry-and-Gaussian-splats-from-Existing-Images-and-Videos-on-Mobile-and-Web)
  informed the separation between adding media, reviewing it and exploring a
  result. TwinForge still processes locally and never implies an uploaded video
  has already become valid geometry.
- [Matterport's digital twin toolbox overview](https://matterport.com/blog/tips-any-business-taking-full-advantage-digital-twin-toolbox)
  informed keeping exploration separate from deliberate measurement tools.
  Matterport support pages were also checked, but their current public rendering
  did not expose enough content to substantiate detailed interaction claims.

The resulting design is deliberately quiet: graphite surfaces, one restrained
mint accent, local Manrope typography, consistent action targets and limited
motion. No copied screenshots, proprietary product assets or remote fonts are
shipped.

## Information architecture

| Area | Main responsibility |
| --- | --- |
| Scenes | Search, filter, review cards and open a saved space |
| Add video | Explicit local copy, inspection and processing review |
| Activity | Follow jobs, inspect issues and open successful results |
| Import & restore | Restore packages or reconnect existing reconstructions |
| Setup & storage | Processing readiness, storage and transfer recovery |
| Scene workspace | Inspect, measure and optionally set a uniform scale |

Navigation is functional, with a visible selected state. Section hashes retain
the chosen library area across reloads. There is no decorative button that
pretends to open a local directory. The local-computer note is passive status,
not an action.

Scene cards use an actual source photo, explicitly identified as such, not a
fabricated scene thumbnail. Available cards open through their photo, title or
prominent **Open scene** action. A retained successful run can still be opened
when a later attempt fails. Version selection, inline rename and reversible
archiving are under **Manage scene**. Empty searches offer filter recovery;
an empty library offers an actual upload action.

The workspace preserves its existing tool IDs and geometry semantics. A visible
**Back to scenes** action replaces the breadcrumb-like text link. Measurement
tools come before the collapsed **Versions & downloads** section. Source-photo
intrinsic aspect ratio and pixel correspondence mapping are unchanged.

## Opening failure found and corrected

Linked scene cards previously checked only whether files existed. Opening the
same scene additionally checked the configured import roots. Restarting without
the linked folder enabled therefore produced a Ready card followed by a rejected
opening request. The frontend then incorrectly appended a WebGL requirement to
every error, including ordinary server failures.

The new lightweight availability preflight shares the exact path-confinement
function used by source validation. Missing, inaccessible and out-of-root files
do not advertise an opening action. Fixed public guidance distinguishes a
missing source from a folder that has not been enabled. Direct opening requests
receive the same guidance without exposing private paths. Original hash and
mapping validation remain authoritative and unchanged. Preflight does not claim
to prove artifact integrity; a subsequent file change can still fail safely.

Linked folders must remain explicitly enabled with `--import-root` on each
application start. The update does not silently broaden access or trust a path
just because it was stored previously. Managed scene/package access remains
confined to its owning run. **Reconnect source** discovers only allowed folders;
**Import & restore** also offers self-contained package recovery.

An opening error provides **Back to scenes** and **Try again**. Only failure to
create the Three.js renderer is described as a browser WebGL/hardware-acceleration
problem. Video playback starts muted and requires user interaction; no preview
autoplays.

## Verification and remaining acceptance

Regression coverage includes:

- real library, activity and upload-review module initialization and navigation
  in a Node DOM harness using IDs from the shipped HTML;
- available/unavailable cards, opening links, inline rename, filtering, activity
  return and upload focus;
- linked-folder removal/re-enabling across application restarts;
- missing files and symlink confinement;
- HTTP card/opening agreement and private-path-safe recovery messages;
- existing observation, pixel selection, asynchronous workspace, calibration,
  export and video admission tests.

The DOM harness does not render CSS or WebGL. The computer-use inventory exposed
no connected browser or application during this update, so fresh rendered visual
acceptance, actual responsive layout, keyboard navigation and a real scene's
appearance remain manual acceptance items. Do not describe these as verified
browser screenshots or claim WCAG conformance.

Final automated verification: **496 passed, 1 skipped** in the lightweight
suite. The skipped case is the explicitly opt-in real MapAnything smoke test;
no neural inference was started for this UI update. Ruff lint and formatting
checks passed, as did syntax checks for the four changed JavaScript modules.
Focused presentation tests were also rerun after the last stylesheet adjustment.

Manual acceptance after restarting the application with the same library and
the required import roots:

1. Open Scenes. Check card photos, names, states and clear opening actions.
2. Open a valid saved scene through its photo and through **Open scene**.
   Return using **Back to scenes**.
3. Switch all four navigation sections, reload, and check the selected section.
4. Search a nonexistent name and clear filters. Rename and archive/restore a
   disposable scene.
5. Open Add video, then close it; keyboard focus returns to Add video. Do not
   start an expensive processing run merely to review the visual design.
6. Check a deliberately unavailable disposable linked source. It should offer
   recovery rather than a misleading Ready state or WebGL diagnosis.
7. In the workspace, inspect a source photo, replay an observation, and expand
   Versions & downloads. Existing measurement safeguards must remain intact.
8. Check wide desktop and narrow mobile layouts, 200% zoom, reduced-motion
   settings and visible keyboard focus.

## Readability and camera path follow-up

Small labels, metadata, card captions, navigation and helper text now have a
13-pixel minimum, including narrow-screen rules. General workspace text is
15 pixels; larger headings retain their hierarchy rather than being reduced to
the minimum. This is a modest typography increase, not browser-level scaling of
the scene or source-photo coordinates. Actual narrow-screen visual acceptance
still requires a browser.

The original camera path was a thin Three.js line bundled with the camera
frusta. The updated path is independently toggleable and uses thin cylinder
overlays between saved camera centers, with small position markers and distinct
start/end colors. This avoids the documented one-pixel limitation of
[Three.js LineBasicMaterial in WebGL](https://threejs.org/docs/pages/LineBasicMaterial.html).
The cylinders are UI overlays, not a reconstructed scene mesh, and are never
included in PLY, GLB, saved coordinates or measurements.

Connections follow timestamps, preserve the original XYZ centers, skip
zero-length segments and break at unavailable poses. There is no spline
smoothing or invented continuous motion. The UI explicitly describes the path
as estimated links between selected views; movement between views is unknown.
Depth testing stays enabled rather than pretending an occluded route is visible
through a surface. Camera-marker visibility remains independent. Switching
scene copies disposes old overlay resources and uses that copy's saved poses.

Tests use the bundled real Three.js implementation to verify cylinder endpoints
against saved camera centers, chronological ordering, missing/duplicate/empty
pose cases, independent visibility and resource disposal. These are geometry
and handler tests, not rendered WebGL acceptance.

Follow-up validation: the full lightweight suite passed with 499 tests and one
explicitly opt-in model smoke test skipped. The focused UI suite passed with
45 tests. Ruff lint and formatting checks passed, as did JavaScript syntax
checks for the workspace and camera-path modules. No neural inference,
reconstruction artifact changes, commit or push was performed.

## Why the scene does not yet look like a solid room

TwinForge currently renders RGB point samples, not textured connected surfaces.
Its default all-frame preview contains at most 500,000 real point rows for
browser responsiveness; full source-frame points remain available separately.
Independent per-view depth/pose disagreement can additionally make surfaces
look doubled or fuzzy. More opaque rendering would not repair those errors.

SkyeBrowse publicly documents both point-cloud and mesh deliverables in its
[output overview](https://www.skyebrowse.com/news/posts/forensic-engineering).
That supports an important representation difference, but does not establish
which rendering layer was used in a particular customer video or reveal its
proprietary reconstruction implementation. Its marketing accuracy statements
are not TwinForge benchmark evidence.

A textured surface renderer would be a separate reconstruction/representation
task, not simply a font or color adjustment. It must not join unrelated noisy
points, fill unseen regions or conceal known shape errors. Existing point-cloud
geometry remains authoritative until a separately evaluated surface method
exists. No scene meshing or backend change is part of this follow-up.

## Researched interaction candidates, not implemented features

The [official SkyeBrowse viewer guide](https://www.skyebrowse.com/news/posts/tutorial-3d-model-viewer)
documents focus navigation, annotations, clipping and screenshot/flythrough
deliverables. The useful next candidates for TwinForge are:

1. A thumbnail/timestamp source-view timeline that makes the existing
   look-from-camera action easier to discover.
2. Double-click focus and saved viewpoints, without changing source geometry.
3. Local screenshots with explicit scale/evidence context.
4. A reversible viewing clip box, clearly separate from deletion or correction.

These are proposals, not claims of delivered features. Photorealistic surface
viewing needs its own evidence-preserving design; automated floor plans,
volumes and generated surfaces should not be borrowed merely because another
product offers them.
