# Generic measurement workspace

## Approved scope

The user approved removing scene-specific measurement defaults and making the viewer substantially more modern and usable. This is a presentation and interaction change, not a reconstruction or calibration algorithm change.

## Design

The point-cloud viewport is the primary workspace. A compact branded header, local variable typography, generous spacing, clear contrast, and a focused inspector replace the dense engineering sidebar. The inspector has three freely selectable steps: Inspect, Measure, and optional Calibrate. Advanced provenance, archive diagnostics, and visibility tools remain available through native expandable sections.

New measurements start with a blank identifier, generic Segment quantity, and no physical length. The identifier accepts the existing storage convention: an initial ASCII letter or digit, followed by letters, digits, underscores, periods, or hyphens, up to 100 characters. UI guidance explains this rather than silently modifying identity. Saved measurements belong to the loaded scene workspace; read-only exported observations are explicitly separate. No object category or particular architectural feature is required.

Calibration requires an active, source-scene, multi-view-qualified reference and a finite positive physical length explicitly entered by the user. Switching reference, clearing it, reopening an archive, or changing the scene copy clears that input. A disabled action explains the missing requirement. Existing calibration reports remain readable, but their control length is never a new-reference default. A single uniform scale does not certify or repair shape accuracy.

Loading, endpoint selection, save results, and errors have readable status messages. Controls remain keyboard accessible, with visible focus, descriptive labels, minimum 44-pixel targets, reduced-motion handling, and a narrow-screen stacked layout. Do not claim full accessibility or browser visual acceptance without actual testing.

Manrope is bundled locally from pinned `@fontsource-variable/manrope@5.2.8`, with its original OFL-1.1 license. Three.js remains local. No CDN, frontend framework, telemetry, or remote UI dependency is introduced.

## Protected contracts

Original XYZ, point indices, frame and pixel provenance, camera axes, scene-copy request generation guards, archive read-only behavior, uniform-scale semantics, and evidence qualifications remain unchanged. All public source, documentation, tests, and UI copy remain English. Private historical reconstruction and benchmark files are not modified. No inference, Git mutation, commit, push, or integration beyond the viewer is authorized.
