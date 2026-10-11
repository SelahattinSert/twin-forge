# Dependencies and model checkpoint

| Dependency | Purpose | License / notes |
|---|---|---|
| TwinForge source | This repository's own code | Apache-2.0; see [`LICENSE`](../LICENSE) |
| Python 3.12 | Supported TwinForge runtime and MapAnything-recommended environment | PSF License |
| NumPy | Efficient dense point, confidence, and image arrays | BSD-3-Clause |
| OpenCV headless | Blur/exposure, perceptual hash, ORB features, image decoding/resizing | Apache-2.0 (OpenCV 4.5.5+) |
| FFmpeg / ffprobe | Video stream inspection and rotation-aware candidate decoding | LGPL/GPL build-dependent; install a build appropriate to your use |
| PyTorch | MapAnything inference runtime | BSD-style; select an official CPU/CUDA package for the host |
| MapAnything `v1.1.3` (`9d1db2dd728bd8a10e74b15d2eb646e1bf933791`) | Official model and preprocessing API, installed from an immutable Git commit | Apache-2.0 source code |
| DINOv2 source (`facebookresearch/dinov2`) | MapAnything's DINOv2 encoder implementation is fetched through PyTorch Hub | Apache-2.0 source; MapAnything disables fetching separate pretrained DINOv2 weights when loading its full checkpoint |
| `facebook/map-anything-apache` at `00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a` | Default model checkpoint, pinned for reproducible runs | Apache-2.0 model variant |
| pytest / Ruff | Development tests and linting | MIT / MIT |
| Three.js `0.180.0` | Offline local Points viewer and OrbitControls; vendored from the official npm distribution | MIT; included in `src/twinforge/viewer/static/vendor/LICENSE` |
| Manrope, `@fontsource-variable/manrope@5.2.8` | Local Latin variable font, normal style, weights 200–800; system font fallback | OFL-1.1; original license in `src/twinforge/viewer/static/vendor/MANROPE-LICENSE` |

The browser viewer makes no CDN requests. Its Three.js module, core module,
OrbitControls, and license are packaged locally. Source distribution:
[official Three.js npm package](https://www.npmjs.com/package/three/v/0.180.0).
Registry tarball integrity: `sha512-o+qycAMZrh+TsE01GqWUxUIKR1AL0S8pq7zDkYOQw8GqfX8b8VoCKYUoHbhiX5j+7hr8XsuHDVU6+gkQJQKg9w==`.

Manrope is vendored from the pinned `@fontsource-variable/manrope@5.2.8` npm
package. Only `files/manrope-latin-wght-normal.woff2` and the original license
are included. The WOFF2 SHA-256 is
`a30ddcd349703aff7464c34bef3fffdff405ee50c113440d7c8693c02d210972`.
CSS uses `font-display: swap` and a system fallback. The local font, license,
and `workspace-ui.js` module are explicitly allowlisted HTTP resources and
included by the existing wheel package-data rules.

Saved-scene viewing, measurement, and calibration require only the lightweight
NumPy/OpenCV application dependencies and a WebGL-capable browser. They do not
load MapAnything or fetch weights. HDR video ingestion additionally needs FFmpeg
zscale (libzimg) and tonemap filters; failed capability/version probes give setup
guidance. Acceptance uses `.model-cache/huggingface` and `.model-cache/torch` with
`HF_HUB_OFFLINE=1`, the source revision and checkpoint pinned above. Local `.aws`,
`.agents`, `.codex`, samples, output, and model cache directories are excluded from
repository delivery.

The MapAnything repository also publishes `facebook/map-anything` under CC-BY-NC 4.0; TwinForge does not default to it. Check the license terms for the exact checkpoint you use. Repository source licensing does not automatically determine checkpoint licensing.

References: [MapAnything official repository and model license table](https://github.com/facebookresearch/map-anything), [MapAnything v1.1.3 release](https://github.com/facebookresearch/map-anything/releases/tag/v1.1.3), [MapAnything package metadata](https://github.com/facebookresearch/map-anything/blob/main/pyproject.toml), [DINOv2 source license](https://github.com/facebookresearch/dinov2/blob/main/LICENSE), [OpenCV license](https://opencv.org/license/), [PyTorch installation selector](https://pytorch.org/get-started/locally/).
