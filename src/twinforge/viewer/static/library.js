import { sceneFetch, workspaceURL } from '/scene-client.js';
import { mountUploadReview } from '/upload-review.js';
import { mountActivity } from '/activity.js';

const byId = id => document.getElementById(id);
const dateFormat = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
let records = [], locateScene = null;
function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
async function request(url, method = 'GET', value) {
  const response = await sceneFetch(url, { method, ...(value ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) } : {}) });
  if (!response.ok) {
    let message; try { message = (await response.json()).error?.message; } catch { /* Generic private-path error. */ }
    throw new Error(message || 'The operation could not be completed. Check the selected source and configured import roots, then retry.');
  }
  return response.json();
}
function report(error) { byId('library-status').textContent = error.message; byId('library-status').classList.add('error'); }
async function patch(record, value) { await request(`/api/library/scenes/${record.scene_id}`, 'PATCH', value); await refresh(); }
function navigate(page) {
  const pages = { scenes: ['Scenes', 'Your scenes', 'From a video to a space you can explore. Open a scene to get started.'],
    imports: ['Import & restore', 'Bring your scenes back', 'Restore a complete package or link a reconstruction already on this computer.'],
    settings: ['Setup & storage', 'Your local environment', 'Prepare processing, check storage and recover interrupted transfers.'],
    activity: ['Activity', 'Work in progress', 'Follow processing runs and return to completed scenes.'] };
  for (const key of Object.keys(pages)) {
    byId(key === 'activity' ? 'activity-panel' : `page-${key}`).hidden = key !== page;
    const nav = byId(key === 'activity' ? 'show-activity' : `nav-${key}`);
    if (key === page) nav.setAttribute('aria-current', 'page'); else nav.removeAttribute('aria-current');
  }
  const [label, title, description] = pages[page];
  byId('page-label').textContent = label; byId('page-title').textContent = title;
  byId('page-description').textContent = description;
  document.title = `${label} — TwinForge`;
  globalThis.history?.replaceState(null, '', `#${page}`);
}
function render() {
  const query = byId('search-scenes').value.toLocaleLowerCase('en-GB');
  const status = byId('status-scenes').value;
  const visible = records.filter(record => record.name.toLocaleLowerCase('en-GB').includes(query) &&
    (status === 'archived' ? record.archived : !record.archived && (status === 'all' || record.status === status)));
  visible.sort(byId('sort-scenes').value === 'name' ? (a, b) => a.name.localeCompare(b.name, 'en-GB') : (a, b) => b.updated_at.localeCompare(a.updated_at));
  const list = byId('scene-list'); list.replaceChildren();
  const active = records.filter(record => !record.archived);
  byId('scene-count').textContent = active.length;
  byId('nav-scene-count').textContent = active.length;
  byId('ready-count').textContent = active.filter(record => record.ready_available || record.status === 'ready').length;
  byId('processing-count').textContent = active.filter(record => ['queued', 'running', 'validating_output', 'cancelling'].includes(record.status)).length;
  if (!visible.length) {
    const onlyArchived = records.length > 0 && !active.length && status === 'all' && !query;
    const empty = element('div', '', 'empty-scenes');
    empty.append(element('span', '⌁', 'empty-icon'), element('h2', onlyArchived ? 'Your scenes are archived' : records.length ? 'No scenes found' : 'Your first space starts here'),
      element('p', onlyArchived ? 'Archived scenes are still saved. Open the archive to explore or restore them.' : records.length ? 'Try a different name or clear the filters to see your scenes.' : 'Add a video of a space you know. We will inspect it before you choose to process it.'));
    const action = element('button', onlyArchived ? 'Show archived scenes' : records.length ? 'Clear filters' : 'Add your first video', 'primary');
    action.onclick = () => { if (!records.length) byId('add-video').click(); else { byId('search-scenes').value = ''; byId('status-scenes').value = onlyArchived ? 'archived' : 'all'; render(); } };
    empty.append(action); list.append(empty); return;
  }
  for (const record of visible) {
    const card = element('article', '', 'scene-card');
    card.setAttribute('data-state', record.status);
    const figure = document.createElement('figure'); const image = document.createElement('img');
    const fallback = element('span', 'Preview unavailable', 'preview-fallback'); fallback.hidden = true;
    image.src = record.thumbnail_url; image.alt = `Source photo for ${record.name}`; image.loading = 'lazy';
    image.onerror = () => { image.remove(); fallback.hidden = false; };
    const managed = record.source_kind === 'managed_video';
    const canOpen = Boolean(record.ready_available || record.status === 'ready');
    const title = element('h2', ''), body = element('div', '', 'scene-card-body');
    if (canOpen) {
      const photoLink = element('a', ''); photoLink.href = workspaceURL(record); photoLink.setAttribute('aria-label', `Open ${record.name}`); photoLink.append(image); figure.append(photoLink);
      const titleLink = element('a', record.name); titleLink.href = workspaceURL(record); title.append(titleLink);
    } else { figure.append(image); title.textContent = record.name; }
    figure.append(fallback, element('figcaption', managed ? 'Source video · local copy' : record.source_kind === 'package' ? 'Restored scene · local package' : 'Source photo · linked original'));
    body.append(title, element('p', dateFormat.format(new Date(record.created_at)), 'scene-date'));
    const labels = { ready: 'Ready to view', ready_to_start: 'Ready to start', queued: 'Queued', running: 'Running',
      validating_output: 'Validating output', cancelling: 'Cancelling', failed: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted', source_unavailable: 'Source unavailable' };
    body.append(element('p', `${labels[record.status] || 'State unavailable'} · ${record.scale_label}`, 'scene-state'));
    const actions = element('div', '', 'card-actions');
    if (canOpen) { const open = element('a', record.status === 'ready' ? 'Open scene' : 'Open saved scene', 'open-scene'); open.href = workspaceURL(record); actions.append(open); }
    else if (record.status === 'source_unavailable') {
      body.append(element('p', record.availability_message || 'The original is missing or its folder is not enabled. Reconnect the source or restore a saved package.', 'scene-help'));
      if (!managed && record.source_kind !== 'package') { const locate = element('button', 'Reconnect source'); locate.onclick = () => openImport(record).catch(report); actions.append(locate); }
      else { const restore = element('a', 'Restore a saved package', 'back-link'); restore.href = '/#imports'; actions.append(restore); }
    }
    if (record.latest_job && record.latest_job.state !== 'ready') {
      const progress = element('button', ['failed', 'cancelled', 'interrupted'].includes(record.status) ? 'Review issue' : 'View progress');
      progress.onclick = () => activity.show(record.latest_job.job_id).catch(report); actions.append(progress);
    }
    if (managed) {
      const review = element('button', canOpen ? 'Review video' : record.status === 'ready_to_start' ? 'Review & process' : 'Review video'); review.onclick = () => uploads.review(record); actions.append(review);
    }
    body.append(actions);
    const menu = element('details', '', 'scene-menu'); menu.append(element('summary', 'Manage scene'));
    if (!managed || record.default_run_id) {
    const label = element('label', 'Selected version'); const versions = document.createElement('select'); versions.setAttribute('aria-label', `Selected version for ${record.name}`);
    for (const version of record.versions) versions.append(new Option(version.label, version.version_id));
    versions.value = record.default_version_id; versions.onchange = () => patch(record, { default_version_id: versions.value }).catch(report); label.append(versions); menu.append(label);
    }
    const tools = element('div', '', 'buttons');
    const form = element('form', '', 'rename-form'); form.hidden = true;
    const nameLabel = element('label', 'Scene name'), name = element('input', ''); name.value = record.name; name.required = true; name.maxLength = 500;
    name.setAttribute('aria-label', `New name for ${record.name}`); nameLabel.append(name);
    const save = element('button', 'Save name'); save.type = 'submit';
    const cancel = element('button', 'Cancel'); cancel.type = 'button'; cancel.onclick = () => { form.hidden = true; rename.focus(); };
    const formActions = element('div', '', 'buttons'); formActions.append(save, cancel); form.append(nameLabel, formActions);
    form.onsubmit = async event => { event.preventDefault(); if (!name.value.trim()) return; save.disabled = true; try { await patch(record, { name: name.value.trim() }); } catch (error) { report(error); } finally { save.disabled = false; } };
    const rename = element('button', 'Rename'); rename.onclick = () => { form.hidden = false; name.focus(); name.select(); };
    const archive = element('button', record.archived ? 'Restore' : 'Archive'); archive.onclick = () => patch(record, { archived: !record.archived }).catch(report);
    tools.append(rename, archive); menu.append(tools, form); body.append(menu); card.append(figure, body); list.append(card);
  }
}
async function refresh() {
  const result = await request('/api/library/scenes'); records = result.scenes; render();
  byId('library-status').textContent = result.issues.length ? `${result.issues.length} scene record(s) unavailable. Other scenes can still be opened.` : `${records.length} scene(s) in your local library.`;
  byId('library-status').classList.remove('error');
  const storage = await request('/api/storage');
  const amount = key => `${(storage[key] / 1024**2).toFixed(1)} MiB`;
  byId('storage-info').textContent = `Linked originals: ${amount('linked_original_bytes')}. Managed videos: ${amount('managed_video_bytes')}. Saved scenes and workspaces: ${amount('retained_scene_workspace_bytes')}. Disposable previews: ${amount('disposable_cache_bytes')}. Retained exports: ${amount('retained_export_bytes')}. Incomplete transfers: ${amount('incomplete_upload_bytes')}.`;
}
async function openImport(record = null) {
  navigate('imports');
  locateScene = record; const choices = await request('/api/library/imports');
  byId('import-panel').hidden = false; byId('import-heading').textContent = record ? 'Locate matching source' : 'Link an existing scene';
  byId('import-choice').replaceChildren(...choices.scenes.map(item => new Option(`${item.label} · ${item.choice_id.slice(-8)}`, item.choice_id)));
  byId('mapping-choice').replaceChildren(new Option('Start without a historical mapping', ''), ...choices.workspaces.map(item => new Option(`${item.label} · ${item.choice_id.slice(-8)}`, item.choice_id)));
  byId('mapping-choice').disabled = Boolean(record); byId('import-name').value = record?.name || choices.scenes[0]?.label || '';
  byId('import-note').textContent = choices.scenes.length ? (choices.truncated ? 'Discovery limit reached. Configure a narrower import root to find more scenes.' : 'Choose exactly one source to register.') : 'No saved scenes found. Start the application with --import-root pointing to a folder containing saved scenes.';
  byId('import-choice').focus();
}
byId('show-import').onclick = () => openImport().catch(report);
byId('package-form').onsubmit = async event => {
  event.preventDefault(); const file = byId('package-file').files[0]; if (!file) return;
  const button = event.submitter; button.disabled = true;
  byId('library-status').textContent = 'Transferring and validating saved package…';
  try {
    const response = await sceneFetch('/api/packages/open', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
    if (!response.ok) throw new Error('Package could not be restored. Check package integrity, free disk space, and active processing.');
    window.location.href = workspaceURL(await response.json());
  } catch (error) { report(error); } finally { button.disabled = false; }
};
byId('cancel-import').onclick = () => { byId('import-panel').hidden = true; };
const activity = mountActivity({ request, refresh, report, onShow: () => navigate('activity'), onClose: () => navigate('scenes') });
const uploads = mountUploadReview({ request, refresh, report, start: activity.start, onShow: () => navigate('scenes') });
for (const page of ['scenes', 'imports', 'settings']) byId(`nav-${page}`).onclick = () => navigate(page);
byId('refresh-scenes').onclick = () => refresh().catch(report);
if (['imports', 'settings', 'scenes', 'activity'].includes(location.hash.slice(1))) navigate(location.hash.slice(1));
globalThis.addEventListener('hashchange', () => { if (['imports', 'settings', 'scenes', 'activity'].includes(location.hash.slice(1))) navigate(location.hash.slice(1)); });
for (const id of ['search-scenes', 'sort-scenes', 'status-scenes']) byId(id).addEventListener('input', render);
byId('import-form').onsubmit = async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  try {
    const value = { choice_id: byId('import-choice').value, name: byId('import-name').value };
    if (byId('mapping-choice').value && !locateScene) value.workspace_choice_id = byId('mapping-choice').value;
    await request(locateScene ? `/api/library/scenes/${locateScene.scene_id}/locate` : '/api/library/scenes', 'POST', value);
    byId('import-panel').hidden = true; await refresh(); navigate('scenes');
  } catch (error) { byId('import-note').textContent = error.message; } finally { submit.disabled = false; }
};
refresh().catch(report);
