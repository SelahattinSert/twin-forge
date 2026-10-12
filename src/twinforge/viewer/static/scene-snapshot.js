// An annotated viewing export, never a measurement or geometry export.
export function snapshotLines(context, title, note) {
  const cutaway = context.clip.enabled ? `ON (view cropped)${context.clip.ranges ? ` | XYZ ranges: ${context.clip.ranges.map(pair => pair.join('–') + '%').join(', ')}` : ''}` : 'off';
  return [title.trim() || 'TwinForge scene view', `Scene: ${context.scene_name} | Copy: ${context.scene_copy}`,
    `Scale: ${context.scale.type}${context.scale.meters_per_unit == null ? '' : ` | meters per unit: ${context.scale.meters_per_unit}`}`,
    `Displayed: ${context.display_label} | ${context.display_count} | Color: ${context.color_mode}`,
    `Selected source: ${context.selected_frame_id ?? 'none'} | Clip box: ${cutaway} | Hidden views: ${context.hidden_frame_count} | Hidden ROIs: ${context.hidden_roi_count}`,
    `Camera path: ${context.path_visible ? 'shown' : 'hidden'} | Camera markers: ${context.cameras_visible ? 'shown' : 'hidden'} | Measurement overlay: ${context.reference_id || 'none'}`,
    'Approximate observed geometry. Scale does not verify shape accuracy. This image is not a metric accuracy certificate.',
    ...(note.trim() ? [`Note: ${note.trim()}`] : []),
    `Manifest SHA-256: ${context.manifest_sha256}`, `Point cloud SHA-256: ${context.point_cloud_sha256}`,
    `Captured: ${context.captured_at}`];
}

function wrappedLines(context, lines, width) {
  const result = [];
  for (const line of lines) {
    let row = '';
    // Character wrapping also bounds long names, URLs and SHA-256 identifiers.
    for (const char of line.replace(/[\r\n\t]/g, ' ')) {
      if (row && context.measureText(row + char).width > width) { result.push(row); row = ''; }
      row += char;
    }
    result.push(row);
  }
  return result;
}

export function composeSnapshot(source, context, title, note, createCanvas = () => document.createElement('canvas')) {
  if (!source.width || !source.height) throw new Error('The 3D view is not ready for capture.');
  if (title.length > 80 || note.length > 500) throw new Error('Use a title of at most 80 characters and a note of at most 500 characters.');
  const canvas = createCanvas();
  const ratio = Math.min(1, 1920 / source.width, 1440 / source.height);
  const imageWidth = Math.max(1, Math.round(source.width * ratio));
  const imageHeight = Math.max(1, Math.round(source.height * ratio));
  canvas.width = Math.max(640, imageWidth);
  let drawing = canvas.getContext('2d');
  if (!drawing) throw new Error('This browser could not prepare the screenshot.');
  drawing.font = '15px system-ui, sans-serif';
  const lines = wrappedLines(drawing, snapshotLines(context, title, note), canvas.width - 40);
  canvas.height = imageHeight + 32 + lines.length * 23;
  drawing = canvas.getContext('2d'); drawing.fillStyle = '#101820'; drawing.fillRect(0, 0, canvas.width, canvas.height);
  drawing.drawImage(source, Math.floor((canvas.width - imageWidth) / 2), 0, imageWidth, imageHeight);
  drawing.font = '15px system-ui, sans-serif'; drawing.textBaseline = 'top';
  lines.forEach((line, index) => { drawing.fillStyle = index === 0 ? '#a5edcf' : '#d5e1e7'; drawing.fillText(line, 20, imageHeight + 16 + index * 23); });
  return canvas;
}

export function canvasPNG(canvas) {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The browser could not encode the screenshot.')), 'image/png'));
}

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
