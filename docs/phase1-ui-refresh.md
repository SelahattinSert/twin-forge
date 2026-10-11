# Generic measurement workspace

The viewer uses a large bordered point-cloud stage, a compact TwinForge header,
dark slate surfaces, restrained mint accents, and local Manrope typography.
The inspector separates Inspect, Measure, and optional Calibrate into freely
selectable steps. The source camera and saved image remain in a shared card so
they are available throughout measurement. Fit scene and All frames are on the
viewport. This is a presentation and interaction update; it does not improve
reconstruction accuracy or change measurement/calibration algorithms.

## Reference lifecycle

New references have a blank identifier, Segment quantity, and no physical length.
Identifiers follow `[A-Za-z0-9][A-Za-z0-9_.-]{0,99}` without silent rewriting.
Saved references reopen from the loaded scene's workspace. Exported source
observations have a separate read-only selector and retain their original
provenance and once-scaled display lines. New reference exits either selection.
Changing identity or quantity clears picks and old evidence selection; finish
naming the reference before selecting endpoints.

The physical length is cleared on reference changes, saved/archive selection,
New reference, and scene-copy switching. It is never filled from a saved control
or archive. One shared eligibility helper drives both the disabled calibration
action and its POST guard: the active record must match the form, belong to the
source workspace, be writable, and carry the existing server-produced
`calibration_qualified` evidence. The explicit length must be finite and greater
than zero. Existing server validation is authoritative. Already-calibrated
scenes and existing derived copies cannot be exported again; reports remain
readable and the existing copy can be selected. A directly reopened calibrated
export displays its validated frozen control and control-excluded checks in
Calibrate as read-only information. Measure retains its separate source archive
and provenance details. If that archive cannot be validated, Calibrate explains
why the frozen report is unavailable instead of claiming no calibration exists.

Async reference loading has a generation guard, so an old response cannot reopen
a reference after New reference or a copy switch. Scene-copy metadata and preview
still commit together only for the current generation. Saved-count refreshes
use the active copy route and cannot replace newer copy metadata. Copy identity
has its own generation counter: All frames and Full frame points can change the
display without discarding a pending same-scene reference open or observation
save. Actual copy/reference changes still reject obsolete responses. Calibration
and copy-loading flags are independent. Ordinary identifier typing does not
rebuild the GPU cloud or reload the source image.

## Evidence and controls

Readable summaries stay visible while native expandable sections hold all
numerical measurement evidence, raw model confidence, artifact hashes, archive
JSON, pixel diagnostics, and manual visibility controls. Picking, saving,
loading, errors, and eligibility use text status messages with live regions.
Source image sizing preserves its intrinsic aspect ratio and the original pixel
mapping formula; no decorative crop or letterbox is introduced.

Native buttons support keyboard activation. Step buttons expose their selected
state with `aria-pressed`; hidden panels leave the keyboard sequence. Controls
have 44-pixel minimum targets, visible focus, explicit labels, and at least
14-pixel body text. Layout rules stack the viewport and inspector at narrow
widths, including a 320-pixel target; fields and button rows can wrap. Reduced
motion disables CSS transitions and initial/recreated orbit damping.

## Assets and verification limits

The font is `@fontsource-variable/manrope@5.2.8`, OFL-1.1, bundled locally with
its original license. Latin WOFF2 SHA-256:
`a30ddcd349703aff7464c34bef3fffdff405ee50c113440d7c8693c02d210972`.
No framework, CDN, telemetry, or remote UI dependency was added.

Automated checks parse actual HTML, execute production presentation helpers and
handlers in Node, preserve existing copy-generation and archive scalar tests,
and cover module/font/license allowlisting and HTTP content types. Node stubs
exercise state transitions without rendering WebGL. These are not rendered
browser tests. The permitted UI inventory in this environment has no enabled
apps or browsers, so visual acceptance at 320 pixels, real keyboard/screen-reader
behavior, zoom, and browser rendering remain unverified. No full accessibility
or WCAG-conformance claim is made.

Final lightweight verification: **283 tests passed; 1 opt-in model smoke test
was skipped**. Ruff, formatting, and both JavaScript syntax checks passed. The
offline wheel contains byte-identical current UI assets and no private scene
data. Read-only HTTP checks passed against four existing scenes; protected
reconstruction and benchmark hashes remained unchanged. Independent engineering
reviews approved the update after the asynchronous status issues were fixed.
Scene-copy switching also clears a cancelled saved-reference loading message;
obsolete responses cannot reopen it. These checks do not replace the browser
acceptance still required above.
