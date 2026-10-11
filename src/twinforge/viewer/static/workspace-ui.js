// Presentation state only. Geometry and evidence remain authoritative on the server.
export function resetReferenceState(state, next = {}) {
  return { ...state, referenceId: '', quantity: 'segment', measurement: null,
    ...next, physicalLength: '' };
}

export function calibrationEligibility(state) {
  const reject = reason => ({ eligible: false, reason });
  if (state.loading) return reject('Wait for the scene or reference to finish loading.');
  if (state.sceneVariant !== 'source') return reject('Switch to the source scene to calibrate.');
  if (state.calibratedScene) return reject('This scene already has calibrated scale. Its frozen report or archive availability is shown in this panel.');
  if (state.derivedAvailable) return reject('A calibrated copy is already saved. Open it with the scene copy selector; its report remains below.');
  if (!state.measurement) return reject('Open a qualified saved reference in Measure first.');
  if (state.measurement.read_only) return reject('Archived observations are read-only. Open a saved reference from this scene.');
  if (state.referenceId !== state.measurement.record.reference_id || state.quantity !== state.measurement.record.quantity)
    return reject('Save or reopen the current reference before calibrating.');
  if (state.measurement.evidence?.calibration_qualified !== true)
    return reject('This reference needs qualified multi-view evidence. Review its measurement details.');
  const physicalValue = Number(state.physicalLength);
  if (!String(state.physicalLength ?? '').trim() || !Number.isFinite(physicalValue) || physicalValue <= 0)
    return reject('Enter a finite physical length greater than zero.');
  return { eligible: true, physicalValue, reason: `Ready to set scale from ${state.referenceId}. Shape accuracy is not validated.` };
}

export function selectWorkspaceStep(step, byId) {
  for (const name of ['inspect', 'measure', 'calibrate']) {
    byId(`panel-${name}`).hidden = name !== step;
    byId(`step-${name}`).setAttribute('aria-pressed', String(name === step));
  }
}

export function formatCalibrationReport(calibration, report, { archived = false } = {}) {
  const lines = [`${archived ? 'Frozen archived control' : 'Control'}: ${calibration.control_id}; s = ${calibration.scalar.toPrecision(9)}; ${calibration.observations.length} frozen views`,
    `Excluded from check statistics: ${report.excluded_control_id}`, 'Calibrated scale does not validate room shape.'];
  if (archived) lines.unshift('Read-only frozen calibration and checks. The archived control is separate from the active reference.');
  for (const check of report.checks) {
    lines.push(`${check.reference_id}: ${check.status}; scaled median ${check.scaled_median_m === null ? 'unavailable' : check.scaled_median_m.toFixed(4) + ' m'}; error ${check.error_m === null ? 'unavailable' : check.error_m.toFixed(4) + ' m'}`);
    for (const [name, region] of Object.entries(check.local_regions || {})) lines.push(`  ${name}: ${region.scaled_length_m === null ? region.reason || 'unmeasured' : region.scaled_length_m.toFixed(4) + ' m'}; same physical reference`);
  }
  if (report.coverage) lines.push(report.coverage);
  if (report.limitation) lines.push(report.limitation);
  lines.push('Full calibration and independent-check records:', JSON.stringify({ calibration, report }, null, 2));
  return lines.join('\n');
}
