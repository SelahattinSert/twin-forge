# TwinForge Phase 0 architecture

```text
RGB video
   ↓
VideoIngestor ── ffprobe metadata; FFmpeg display-oriented candidate decode
   ↓
KeyframeSelector ── sharpness, exposure, duplicate, ORB overlap and novelty
   ↓
ReconstructionBackend ── MapAnything adapter owns model-specific API/tensors
   ↓
ReconstructionResult ── TwinForge cameras, points, scale and confidence
   ↓
Quality analyzer (including selected timeline coverage) + PLY / GLB / JSON exporters
```

`VideoIngestor` uses FFmpeg tooling so codecs and phone rotation metadata are handled consistently. Candidates are sampled rather than decoding every source frame into the model. `KeyframeSelector` is deterministic for a fixed decoded input and settings. Candidate timestamps are preserved; source frame numbers are approximate on variable-frame-rate footage.

`ReconstructionBackend` separates the normalized TwinForge representation from backend image preprocessing, tensor shapes, model fields, and coordinate conventions. `MapAnythingBackend` follows the official package API (`MapAnything.from_pretrained`, `mapanything.utils.image.load_images`, `model.infer`) and converts returned OpenCV world axes into TwinForge's right-handed Z-up world. Missing backend fields remain unavailable in normalized output.

Before MapAnything inference, its adapter records the dense float32 XYZ payload lower bound implied by image dimensions after `load_images` preprocessing. On CUDA it compares that lower bound to currently free VRAM. This is diagnostic, not a peak-memory prediction: model parameters, activations, auxiliary outputs, allocator overhead, and host-side copies are not included. The adapter uses MapAnything's memory-efficient inference with dense-head minibatch size one; the configured keyframe cap remains TwinForge's explicit workload limit.

The selector evaluates every quality-usable candidate before applying `maximum_keyframes`. If the candidate set exceeds the cap, it keeps a deterministic timestamp-spread subset, including the first and last usable observations, and recomputes ORB overlap/novelty between the final neighbors. Quality output reports the selected timeline span and fraction of video duration; low coverage or missing camera poses yields `CAMERA_TRAJECTORY_INCOMPLETE`.

The Phase 0 scene is point based. PLY is authoritative and carries per-point confidence, source frame IDs, and validity as PLY scalar properties where supplied. Raw points remain in PLY; optional camera-space depth maps are stored in NPZ. GLB is a standards-based `POINTS` primitive filtered to valid points for convenient preview; no mesh is inferred. JSON files contain metadata and references, not dense tensors.

Later phases may evaluate other backends, COLMAP verification, depth fusion, multi-fragment reconstruction, and scale calibration. Those systems are intentionally outside this prototype.
