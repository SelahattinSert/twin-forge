// Report actual evidence without turning internal consistency into accuracy.
export function measurementSummary(value) {
  const evidence = value?.evidence;
  if (!evidence || evidence.observation_count === 0) return 'Select two points on a source photo.';
  const prefix = value.read_only ? 'Saved source observations are read-only in this exported copy. ' : '';
  const reasons = evidence.reasons || [];
  if (evidence.state === 'conflicting_observations') return prefix + 'The selected points do not line up across images. Review the observations. Either correspondence or reconstructed geometry can contribute to disagreement.';
  if (evidence.state === 'consistent_observations' && evidence.calibration_qualified === true) return prefix + 'These observations are consistent. You can set scale using this reference. Shape accuracy is not verified.';
  const actions = [];
  if (evidence.distinct_view_count < 2) actions.push('Add the same points from another image. Repeated observations in one image do not add independent views.');
  if (reasons.includes('physical_endpoint_correspondence_unreviewed')) actions.push('Review and identify physical endpoint correspondence for each observation.');
  if (reasons.includes('pixel_sensitivity_unavailable')) actions.push('Verified pixel support is incomplete or unavailable. Review Technical details; selecting another point cannot guarantee geometry support.');
  if (reasons.includes('source_view_hash_unavailable')) actions.push('Source image provenance is unavailable. Restore the recorded source photo before comparing views.');
  if (reasons.includes('invalid_endpoints')) actions.push('Endpoint geometry is invalid or unsupported. Review the selected points.');
  if (reasons.includes('mixed_reference_or_scene_artifacts')) actions.push('The observations belong to different references or scene artifacts. Review their provenance.');
  if (!['insufficient_evidence', 'consistent_observations'].includes(evidence.state)) return prefix + 'Evidence is unavailable for this reference. Review its technical status.';
  return prefix + (actions.join(' ') || 'More evidence is needed before this reference can be used to set scale. Review Technical details.');
}

export function calibrationSummary(calibration, report) {
  if (!calibration) return 'No scale has been set. You can inspect and measure the source scene.';
  const views = new Set(calibration.observations.map(item => item.source_view_sha256 || item.frame_id)).size;
  const evaluated = (report?.checks || []).filter(check => check.reference_id !== calibration.control_id && check.reference_id !== report.excluded_control_id && check.role === 'check_only' && ['observed_check','frozen_historical_check'].includes(check.status) && Number.isFinite(check.error_m) && Number.isFinite(check.physical_length_m) && check.physical_length_m > 0 && Number.isFinite(check.scaled_median_m));
  const historical = evaluated.filter(check => check.status === 'frozen_historical_check').length;
  return `Scale set from your reference and ${views} source images. Shape accuracy is not verified. ` + (evaluated.length ? `${evaluated.length} evaluated physical-distance comparisons are reported in Technical details; the scale reference is excluded.` + (historical ? ` ${historical} use frozen historical selections, with their recorded inspection limits.` : '') + ' Previously inspected references are not a blind test set.' : 'No evaluated independent physical-distance comparison is available. The scale reference is excluded from independent checks.');
}
