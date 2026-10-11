# Local video-to-scene library

TwinForge's application keeps multiple scenes, observations, processing history,
and saved versions in one local library. After startup, ordinary scene tasks use
the browser: add a video, review it, start processing, open a result, measure,
save versions, and download or restore a package.

## Start the application

Use Python 3.12 and the installation instructions in the [README](../README.md).
Saved-scene viewing and measurements need the lightweight application, a
WebGL-capable browser, and no model weights. Video inspection additionally needs
FFmpeg and ffprobe. Processing needs the documented MapAnything backend and
prepared checkpoint; opening the library does not start inference.

```bash
twinforge app --library output/phase2/library
```

The app binds to `127.0.0.1` and opens its local URL. Keep the application process
running while using the library or processing a video. To open the printed URL
yourself, add `--no-browser`. Use the same `--library` directory on later starts
to retain scenes, names, observations, exports, and defaults.

Existing saved scenes can be discovered only under roots chosen at startup:

```bash
twinforge app --library output/phase2/library \
  --import-root output/saved-scenes --import-root output/verified-mappings \
  --no-browser
```

`--import-root` is repeatable. It must point to an existing directory. Include
the roots containing any required verified mapping proofs. The browser cannot
browse arbitrary host paths. Optional cache overrides are `--hf-home`,
`--hf-hub-cache`, and `--torch-home`; explicit cache environment variables are
also honored. The default caches are `.model-cache/huggingface` and
`.model-cache/torch`. `--upload-limit-gib` adjusts the individual transfer cap;
other storage and validation limits still apply. Run `twinforge app --help` for
all startup options.

## Add and review a video

1. Choose **Add video**, select one `.mp4`, `.mov`, or `.mkv`, then choose
   **Copy and inspect video**. Prefer the original phone file. The application
   copies the original bytes into managed library storage and reports transfer
   progress. Inspection decodes one display-oriented, color-correct still;
   it does not load the reconstruction model.
2. Review the duration, encoded and displayed dimensions, codec, color policy,
   and still. Browser video playback may be unavailable for a valid codec;
   the still and FFmpeg inspection remain usable. Check the actual file's
   displayed orientation and dimensions rather than its advertised resolution.
3. Enter a scene name and choose the processing profile. **Save review** retains
   these choices without starting work. **Start processing** also saves the
   current choices before submitting the job.
4. If setup is missing, open **Setup & storage**, read **Processing environment**
   and choose **Check setup**.
   Backend packages must be installed in the application environment using the
   documented installation instructions. **Prepare model** explicitly prepares
   missing checkpoint/cache files; it does not install Python packages. This
   preparation can download several gigabytes and is separate from processing.
5. Choose **Start processing** once setup and input are ready. Return to
   **Scenes** or **Activity** while the owned worker processes the video.

The pinned checkpoint is `facebook/map-anything-apache` at revision
`00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`. Normal processing uses prepared
caches with external network access denied in the worker. A missing dependency
or cache is a setup problem, not permission to silently fetch another model.

| Profile | Default device | Selected-image policy | CUDA inference OOM retries |
| --- | --- | --- | --- |
| Standard scene | CPU | Up to 32 useful images, automatic budget reduction disabled | 0 |
| Quick preview | Automatic | Existing automatic memory budget; fewer views can omit coverage | At most 3, subject to the minimum view count |

Selection can retain fewer useful images than a profile's cap. Advanced device
overrides change the requested device; they do not enable automatic budgeting
for Standard. A 4K source does not imply a 4K inference grid. CPU runs can take
many minutes. The application shows elapsed time, stages, selected images and
actual device when available, rather than inventing a neural progress percentage
or completion time.

## Processing, recovery, and the library

Only one heavy operation owns the processing slot at a time; other jobs queue.
**Activity** retains stage history and diagnostics under **Details**. A live
worker means its process is alive, not proof that its mathematics is advancing.
Scene browsing stays available while processing.

Refreshing a browser or closing its tab does not cancel an accepted job. Reopen
the same application URL to see its saved state. Closing the application itself
interrupts work. Restart reconciles earlier jobs without automatically launching
inference; **Retry as new run** creates a fresh run. Checkpoint resume is not
available. **Cancel** stops the owned worker and its children; partial output
cannot become a Ready scene. Failed or cancelled attempts retain diagnostics.
If earlier worker ownership cannot be established safely, new heavy work remains
blocked with an explanation.

A validated completed run gains **Open scene**. Search names, sort cards, rename
scenes, and choose saved versions under **Manage scene** in **Scenes**. A ready
scene opens through its photo, title or **Open scene** button. Use **Back to
scenes** in the workspace header to return. Identical names are allowed;
the scenes still have separate identities and workspaces. **Archive** hides a
scene from active filters. Use **Archived scenes** and **Restore** to reverse it.
Archiving frees no disk space. **Setup & storage** separates linked originals,
managed videos, workspaces, previews, retained exports, and incomplete transfers.
Permanent scene deletion is not available.

For a saved artifact, open **Import & restore**, choose **Find existing scenes**, select the discovered
source, name it, and optionally select a verified pixel mapping. Linking leaves
the source read-only and starts fresh observations; historical measurements are
not imported. If a linked source moves, **Reconnect source** can reconnect a
matching source found under the configured roots. An unavailable source does
not prevent opening other library entries. Include the source's `--import-root`
on every restart; a path being saved in the library does not grant access to it.
Cards show unavailable sources with recovery guidance instead of an opening
action. **Restore scene package** can restore a complete saved ZIP without a
linked source. Workspace downloads are under **Versions & downloads**.

If an upload fails, use **Discard incomplete local copy** before restarting Add
video. Invalid extensions, mismatched transfer lengths, decode failures, storage
limits, and incomplete copies are rejected without publishing a completed scene.
Keep enough storage for the original, decoded candidates, output, saved versions,
and any exports. Transfer limits are admission bounds, not a guarantee that all
videos below the cap fit in available disk or RAM.

## Explore a saved scene

Use the thumbnail **Source views** timeline to select a source photograph and
**Look from view** to enter its estimated camera position. Double-click visible
points to change the orbit center. **Inspect** also contains named saved
viewpoints and a reversible viewing clip box; **Screenshot** downloads a PNG with
an annotation and scale/evidence context. These controls never correct or delete
source geometry. Saved viewpoints are browser-local and require the same URL
origin (use an explicit `--port` across restarts); they are not part of scene
packages. See [scene exploration tools](viewer-exploration.md) for usage and limits.

## Select and save observations

Open a scene and select **Measure**. Choose a source frame, start a new reference,
and select A and B on its source photo. The large photo editor shows red endpoint
markers and their segment immediately. Letterboxed space outside the image is
not a selectable pixel. Zoom, fit, pan, drag endpoints, Undo, and Clear help
refine a selection. Choose A or B before keyboard arrow nudges; Shift increases
the nudge to ten source pixels. Enter places a missing endpoint at the center.
**Confirm** returns the draft to the form; **Cancel** discards editor changes.
Confirmation is separate from adding the observation.

Identify the same physical endpoints, confirm correspondence, and add the
observation. A saved reference appears in the scene's measurements. Give it a
recognizable display name, reopen its photo/endpoint replay, correct a selection,
or exclude an observation with a reason. Corrections retain history rather than
replacing provenance. New references and different scenes start with separate
selection state. Source image picking requires verified pixel-to-point provenance;
missing mapping can leave it unavailable while 3D inspection remains usable.

The plain result explains the available evidence. One source image calls for
another view. Repeating picks in that image does not add independent views.
Consistent observations can qualify a reference for scale; conflicting
observations call for reviewing endpoint correspondence and geometry. Technical
details retain hashes, view counts, sensitivity, and raw confidence. Internal
consistency is not physical accuracy, and raw confidence is not a probability.
See [measurement rules](phase1-usage.md) for the unchanged engineering thresholds.

## Saved versions and downloads

Calibration is optional and requires a qualified reference before a physical
length is entered. Enter a measured positive length explicitly; no length is
filled in for you. Saving calibration creates a separate immutable version with
frozen observations and reports. One scalar changes XYZ, camera translations,
and supported depth. It cannot fix shape distortion. The scale control is
excluded from independent distance checks.

Use **Saved versions** to switch versions and **Make default** to retain a
preferred opening choice. New calibration does not silently replace the default.
Correct observations in the source version. From a frozen version, a new physical
length can create another calibrated version from the original source geometry;
the saved geometry is not scaled repeatedly.

Choose **Download PLY**, **Download GLB**, or **Download full package**. PLY is
the authoritative point artifact; GLB is an optional point preview and may be
unavailable. A full package includes source photos, geometry, observations,
mapping evidence where required, calibration and frozen reports. It excludes
the original uploaded video and model caches. Source photos can reveal private
spaces, so treat a full package accordingly.

To reopen a full package, use **Open a complete scene package (.zip)** and
**Restore saved scene package** in Scenes. Validation restores a separate
managed scene, without requiring the original linked workspace or copying
sidecars. PLY or GLB alone is not a complete restorable measurement package.
Packages and exports remain on local disk. Active heavy work, policy limits,
insufficient storage, unsupported ZIP structure, or modified hashes can prevent
restoration; the original scene and earlier valid exports remain available.

See [delivery evidence and open acceptance](phase2-delivery.md) for what has
actually been checked. All quality statements remain limited to the recorded
evidence; a Ready scene or calibrated metric scale is not room certification.
