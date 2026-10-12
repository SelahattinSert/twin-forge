// Pure state helpers used by rendering and frame selection.
export function frameSelection(value) {
  if (!value.trim()) return null;
  const frame = Number(value);
  return Number.isInteger(frame) && frame >= 0 ? frame : null;
}

export function visiblePoint(frameId, pixelId, visibility, mappings) {
  if (visibility.hidden_frame_ids.includes(frameId)) return false;
  if (pixelId === null) return true;
  const mapping = mappings.find(item => item.frame_id === frameId);
  if (!mapping) return true;
  const width = mapping.crop_bbox[2] - mapping.crop_bbox[0];
  const u = Number(pixelId) % width, v = Math.floor(Number(pixelId) / width);
  return !visibility.hidden_rois.some(roi => roi.frame_id === frameId && u >= roi.bounds[0] && v >= roi.bounds[1] && u <= roi.bounds[2] && v <= roi.bounds[3]);
}
