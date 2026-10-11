// Application version selection and disk-backed downloads.
export async function mountVersionActions(host, metadata, { sceneId, request, go }) {
  const node = (tag, text) => { const item = document.createElement(tag); item.textContent = text; return item; };
  const record = await request(`/api/library/scenes/${sceneId}`);
  const version = metadata.version;
  const status = node('p', ''); status.setAttribute('role', 'status');
  const select = node('select', ''); select.setAttribute('aria-label', 'Open saved version');
  for (const item of record.versions) { const option = node('option', item.label); option.value = item.version_id; select.append(option); }
  select.value = version.version_id;
  select.onchange = () => { const item = record.versions.find(v => v.version_id === select.value); go(`/scenes/${sceneId}/runs/${item.run_id}/sessions/${item.session_id}`); };
  const makeDefault = node('button', 'Make default'); makeDefault.disabled = record.default_version_id === version.version_id;
  makeDefault.onclick = async () => { try { await request(`/api/library/scenes/${sceneId}`, 'PATCH', { default_version_id: version.version_id }); makeDefault.disabled = true; status.textContent = 'This is now the default displayed version.'; } catch (error) { status.textContent = error.message; } };
  host.replaceChildren(node('h3', 'Saved versions'), select, makeDefault,
    node('p', version.frozen ? 'This version retains frozen observations and reports. To correct observations, open the source version. To change the physical length, save another version from its frozen reference.' : 'New calibrations save a separate version; your selected default stays unchanged.'),
    node('p', 'Full packages contain source photos of your private space. Downloaded exports are retained in local storage.'));
  for (const [kind, title] of [['ply', 'PLY'], ['glb', 'GLB'], ['package', 'full package']]) {
    const button = node('button', `Download ${title}`);
    button.onclick = async () => {
      button.disabled = true; status.textContent = 'Preparing download…';
      try { const result = await request('/api/exports', 'POST', { scene_id: sceneId, version_id: version.version_id, kind });
        if (result.status === 'unavailable') status.textContent = result.message;
        else { const link = node('a', `Download ${title}`); link.href = result.download_url; link.download = ''; status.replaceChildren(link); link.click(); }
      } catch (error) { status.textContent = error.message; } finally { button.disabled = false; }
    };
    host.append(button);
  }
  host.append(status); host.hidden = false;
  if (version.frozen) {
    const prefix = `/api/scenes/${sceneId}/runs/${version.run_id}/sessions/${version.session_id}`;
    const calibration = await request(`${prefix}/calibration`);
    const form = node('form', '');
    const length = node('input', ''); length.type = 'number'; length.min = '0'; length.step = 'any'; length.required = true;
    const lengthLabel = node('label', 'New physical length in meters'); lengthLabel.append(length);
    const name = node('input', ''); name.maxLength = 500; name.value = `${version.label} revised`;
    const nameLabel = node('label', 'New version name'); nameLabel.append(name);
    const preview = node('p', 'Enter a measured length. Scale applies uniformly and cannot fix shape distortion.');
    length.oninput = () => { const scalar = Number(length.value) / calibration.reconstructed_median; preview.textContent = Number.isFinite(scalar) && scalar > 0 ? `Uniform scale: ${scalar.toPrecision(6)} × original source geometry. Shape accuracy is not verified.` : 'Enter a finite positive length in meters.'; };
    const submit = node('button', 'Save another calibrated version'); submit.type = 'submit';
    form.append(node('h4', `Frozen reference: ${calibration.control_id}`));
    for (const observation of calibration.observations.slice(0, 2)) {
      const image = node('img', ''); image.src = `${prefix}/frames/${observation.frame_id}/image`; image.alt = `Frozen control source photo ${observation.frame_id}`; image.width = 100; form.append(image);
    }
    form.append(lengthLabel, nameLabel, preview, submit);
    form.onsubmit = async event => {
      event.preventDefault(); const physical = Number(length.value);
      if (!length.value.trim() || !Number.isFinite(physical) || physical <= 0) { status.textContent = 'Enter a finite positive length.'; return; }
      submit.disabled = true;
      try { const saved = await request(`${prefix}/calibration`, 'POST', { reference_id: calibration.control_id, physical_value: physical, physical_unit: 'm', label: name.value });
        go(`/scenes/${sceneId}/runs/${saved.version.run_id}/sessions/${saved.version.session_id}`);
      } catch (error) { status.textContent = error.message; } finally { submit.disabled = false; }
    };
    host.append(form);
  }
}
