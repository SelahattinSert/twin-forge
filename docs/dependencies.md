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

The MapAnything repository also publishes `facebook/map-anything` under CC-BY-NC 4.0; TwinForge does not default to it. Check the license terms for the exact checkpoint you use. Repository source licensing does not automatically determine checkpoint licensing.

References: [MapAnything official repository and model license table](https://github.com/facebookresearch/map-anything), [MapAnything v1.1.3 release](https://github.com/facebookresearch/map-anything/releases/tag/v1.1.3), [MapAnything package metadata](https://github.com/facebookresearch/map-anything/blob/main/pyproject.toml), [DINOv2 source license](https://github.com/facebookresearch/dinov2/blob/main/LICENSE), [OpenCV license](https://opencv.org/license/), [PyTorch installation selector](https://pytorch.org/get-started/locally/).
