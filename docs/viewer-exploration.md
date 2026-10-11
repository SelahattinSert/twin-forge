# Scene exploration tools

These tools operate on an existing saved point cloud. They do not start
inference, change camera estimates, calibrate scale, reconstruct surfaces or
modify source XYZ. All shipped controls and messages are in English.

## Source-view timeline

Open **Source views** below the 3D viewport to show saved photographs in
timestamp order, with frame identifiers and timestamps. The strip starts
collapsed to leave more space for the scene. Its summary shows the view count;
click the summary again to hide the photographs. Native disclosure keyboard
controls (Enter/Space on the summary) are available. Selecting a frame elsewhere
does not reopen the strip or scroll the page to a hidden thumbnail.
Select a thumbnail to
highlight its camera and load its original source photo in the inspector. The
timeline stays synchronized with the frame selector and camera-marker clicks.
It does not replace the measured image-coordinate picking editor.

- **Previous/Next source view** moves one saved observation at a time.
- **Look from view** moves the viewing camera to the selected estimated pose.
  It is unavailable when that view has no saved pose.
- Focus a thumbnail and use Left/Right, Home or End to navigate with a keyboard.
- A missing photo displays a fallback instead of implying evidence exists.

These are selected observations, not a full video replay. Thumbnail cropping is
presentation-only; original source-photo pixels and their mappings are unchanged.

## Hover source previews

Move the pointer over a camera icon or camera-path position to see
its chronological view number, original frame identifier, timestamp and source
photograph. A small screen-space ring identifies the hovered position. The photo
uses its original aspect ratio and has a **Look from view** action: clicking it
selects that exact source frame and enters its estimated camera pose.

Clicking a point-cloud sample still shows its original PLY point index in the
inspector and selects its recorded source frame when provenance is available.
Dense point samples and camera-frustum wireframes no longer automatically open
hover cards: leaving an icon must not immediately replace its card with a popup
from the dense surface below it. Missing photos display a
fallback; absent camera poses disable the camera-view action. The preview is the
recorded RGB photo, not an independently rendered or generated 3D reconstruction.

Leaving the camera target schedules dismissal after a 70 ms bridge tolerance,
followed by a 90 ms fade. Moving into the preview cancels dismissal so its photo
remains clickable. Leaving the card also dismisses it, including when moving
back onto the canvas without another pointer move. The close button and Escape
remain available but are not required. Keyboard focus preserves the card;
mouse focus does not pin it. Entry uses a 120 ms opacity/4-pixel-rise animation,
with cancellation-safe reversals and reduced-motion support.
Hover previews are disabled during 3D endpoint collection and suppressed during
dragging or zooming. Touch users can use the existing source-view timeline.
Pointer events are coalesced to one lookup per animation frame without a fixed
hover delay. Only camera targets are queried for automatic cards; no dense
point-cloud index is allocated or scanned for this interaction. The bounded
screen-space point index remains available to the internal diagnostic picker
and its standalone microbenchmark. Hidden/clipped camera targets are not offered.
Measurement endpoint picking is unchanged.
Image-load generations prevent a late response from showing the previous frame.
Switching scene copies, replacing point bundles or resizing dismisses stale cards.

Camera icons are small, depth-tested billboards at saved camera centers. They
share one local SVG texture and are presentation overlays, not new PLY geometry.
The camera visibility control also hides these icons.

Timeline and hover photos use read-only, aspect-preserving JPEG thumbnails with
a maximum 320-pixel long edge. The full-size inspector/photo picking editor
still uses the original image and original pixel mapping. Server thumbnail
caches are bounded to 32 entries / 4 MiB per active scene service; the hover
card retains at most eight decoded image elements and cancels superseded image
loads. Reusing the image element avoids a duplicate no-store HTTP request.
These caches are in memory, not new files in source reconstruction directories.

## Focus and saved viewpoints

Double-click a visible point in the 3D viewport to make it the orbit center.
The viewing camera translates with the center so its relative viewing direction
and distance do not jump. Empty space does not substitute an invented surface.
Focus is disabled while **Pick in 3D** is collecting measurement endpoints.
Normal inspection waits briefly to distinguish a single click from a focus
double-click; endpoint picking remains immediate.

In **Inspect → Saved viewpoints**, enter a name and choose **Save current view**.
Choose an entry to open, rename or remove it. Up to 20 views are stored per scene
copy. A saved view includes camera position, orbit target, up vector, field of
view, clipping distances, selected source frame and viewing clip settings.
Point filtering, measurement drafts and calibration are not part of the saved
view. Opening a view does not replace those states.

Views are stored in browser local storage, scoped to the application session
identity, manifest hash, point-cloud hash and source/derived copy. They are not
written into original artifacts or included in scene packages. Browser storage
is also scoped to the URL origin, including its port. To retain access after
restarting the application, use the same browser profile, hostname and explicit
port, for example:

```bash
twinforge app --library output/phase2/library --port 8765
```

Include the same required `--import-root` arguments for linked scenes. The
default free-port mode can choose a different origin on restart. Clearing browser
site data removes saved viewpoints; it does not remove library scenes. Storage
failures and invalid stored data produce an explanation rather than a false
successful save. Corrupt stored data is not silently overwritten.

## Reversible viewing clip box

Open **Inspect → Viewing clip box**, enable **Enable cutaway**, then adjust the
start/end sliders for X, Y or Z. The percentages describe the full preview's
axis-aligned bounds, not measured architectural distances. A wireframe shows
the active volume. X/Y/Z are the scene's display coordinates; Z-up does not prove
gravity was observed.

The cutaway hides points and overlays outside the volume. Hidden points cannot
be picked or focused through the cutaway. **Reset cutaway · show full volume**
disables it and restores the full viewing volume. Existing manually hidden
views/ROIs remain hidden until their separate visibility control is reset.
Switching source/derived copies resets the cutaway to avoid applying stale
coordinate bounds. A saved viewpoint can explicitly restore its own settings.

The implementation uses world-space clipping planes plus a matching point-index
filter and hit-test guard. Original arrays remain unchanged. No source point is
deleted, no annotation is rewritten, and PLY/GLB/package exports remain complete.
The clip box is a viewing aid, not geometry correction.

## Annotated screenshots

Choose **Screenshot** above the viewport, enter a title and optional note, then
choose **Download annotated PNG**. The image captures the current rendered 3D
view, including visible path, camera and measurement overlays. The footer records:

- scene/copy and scale status;
- displayed frame/point context and color mode;
- selected source frame, active cutaway and manual-visibility counts;
- path/marker visibility and active reference identifier;
- source manifest and point-cloud hashes, capture time and the annotation;
- an explicit statement that approximate geometry is not an accuracy certificate.

The footer note is an image annotation, not a new spatial measurement or a
persistent 3D pin. No physical length is inferred from screenshot pixels. PNGs
can expose private scene imagery and names; share them deliberately.

The renderer renders and copies the canvas synchronously before asynchronous
PNG encoding, avoiding reliance on a retained WebGL drawing buffer. Image content
is bounded to 1920 × 1440 pixels before the context footer, preserving aspect
ratio. Cancelling the dialog or switching copies while encoding suppresses stale
downloads. Download and encoding failures are reported without changing geometry.

## Implementation and validation

- `view-state.js`: scoped browser storage, bounded records, camera state.
- `scene-exploration.js`: timeline, clip primitives and rigid viewing focus.
- `exploration-ui.js`: tool controls, storage errors and capture lifecycle.
- `scene-snapshot.js`: context footer, bounded PNG composition and download.
- `app.js`: connections to actual saved cameras, renderer and point provenance.

The geometry tests use the bundled Three.js implementation. UI tests execute
production modules with a deterministic DOM harness. They check clipping on all
six sides, reset behavior, unchanged XYZ bytes, hidden-point picking, camera
state restoration, storage isolation/limits, timeline keyboard navigation,
thumbnail errors, click/double-click separation, render-before-copy ordering and
stale screenshot cancellation. Static HTTP tests cover serving the new modules.
These tests are not a substitute for rendered browser acceptance.

Validation on 2026-10-11: the full lightweight suite passed with 509 tests and
one explicitly opt-in real model test skipped. After the last click-cancellation
and screenshot-context adjustment, all 58 focused viewing/measurement tests
passed again. Ruff lint, Ruff formatting and JavaScript syntax checks passed.
The browser-control inventory had no enabled browser, so rendered WebGL, PNG
visual appearance and responsive-layout acceptance were not performed. No
neural inference, source-artifact mutation, commit or push was performed.

Collapsed-timeline/source-hover follow-up on 2026-10-11: 517 lightweight tests
passed and the opt-in real model test was skipped. All 66 focused viewer and
measurement tests passed again after the final focus-return/layout adjustment.
Ruff lint/format and JavaScript syntax checks passed. The browser inventory still
had no enabled surface, so actual rendered hover-card appearance and native PNG
download acceptance remain manual checks, not reported successes. This update
did not start inference or change source geometry, benchmarks or scale.

Manual acceptance in a WebGL-capable browser:

1. Restart the application, open an existing saved scene and hard-refresh once.
2. Select thumbnails, previous/next and keyboard controls. Compare the highlighted
   frame with the source photo and camera marker. Test **Look from view**.
   Collapse the timeline and verify the scene regains height. Hover camera/path
   positions and point samples, move onto the card, then click its photo. Verify
   the photo's own source frame is selected, not a previous frame. Check missing
   photos/poses, clipping, dragging, Escape and close behavior.
3. Double-click visible geometry, then orbit. Verify a single click still inspects
   and measurement picks remain immediate, without a focus jump.
4. Save/open/rename/remove a view. Refresh at the same address and verify persistence.
   Verify another scene/copy does not inherit it.
5. Move each clip slider, verify hidden points cannot be picked, then reset. Compare
   point counts and existing measurements before/after. Switch scene copies.
6. Download a PNG with a note, inspect the picture and context footer, then test
   cancelling and an unavailable/disabled browser download.
7. Check narrow windows, 200% zoom, keyboard focus and reduced-motion settings.

Interaction inspiration came from the
[official SkyeBrowse viewer guide](https://www.skyebrowse.com/news/posts/tutorial-3d-model-viewer).
The implementation uses existing saved evidence, not SkyeBrowse outputs.
Rendering behavior follows Three.js documentation for
[world-space clipping planes](https://threejs.org/docs/pages/WebGLRenderer.html)
and [orbit targets](https://threejs.org/docs/pages/OrbitControls.html).
