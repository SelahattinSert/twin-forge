// Local byte transfer, still fallback, explicit setup and saved job submission.
export const playbackFallback = 'Video playback is unavailable in this browser. The file can still be processed.';
export function reviewState(scene, readiness) {
  const valid = ['ready_to_start', 'ready'].includes(scene?.status) && scene.media?.inspection?.decode_ready === true;
  return { inputReady: valid, processingConfigured: Boolean(readiness?.processing_ready),
    canStart: valid && Boolean(readiness?.processing_ready) && Boolean(readiness?.job_launch_available),
    startMessage: readiness?.job_launch_message || 'Start processing will become available with the processing job package.' };
}
export function playbackState(failed, inspection) {
  return { showStill: true, message: failed && inspection?.decode_ready ? playbackFallback : '' };
}

export function mountUploadReview({ request, refresh, report, start, onShow = () => {} }) {
  const byId = id => document.getElementById(id);
  const bytes = value => value == null ? 'Unknown' : `${(value / 1024**2).toFixed(1)} MiB`;
  let selectedScene = null, receipt = null, readiness = null, xhr = null, poll = null;
  let submissionKey = null;
  let nextCursor = null;
  function recoveryStatus(message) {
    byId('transfer-recovery-status').textContent = message;
    byId('video-status').textContent = message;
  }
  async function recoverTransfers(after = null) {
    const page = await request(`/api/uploads${after ? `?after=${encodeURIComponent(after)}` : ''}`);
    const list = byId('incomplete-transfers'); list.replaceChildren();
    const node = (tag, text) => { const element = document.createElement(tag); element.textContent = text; return element; };
    for (const item of page.uploads) {
      const card = node('article', '');
      card.append(node('p', `${item.client_name} · ${item.state} · ${bytes(item.received_bytes)} of ${bytes(item.expected_bytes)}`));
      if (item.error) card.append(node('p', item.error.message));
      const action = (label, run) => { const button = node('button', label); button.type = 'button';
        button.disabled = ['transferring', 'inspecting'].includes(item.state);
        button.onclick = async () => { button.disabled = true; try { await run(); await recoverTransfers(); await refresh(); }
          catch (error) { recoveryStatus(error.message); } finally { button.disabled = false; } };
        card.append(button); };
      if (item.state === 'transferred') action('Finish inspection', async () => {
        const result = await request(`/api/uploads/${item.upload_id}/complete`, 'POST', {
          name: item.client_name.replace(/\.[^.]+$/, '').split(/[\\/]/).pop() || 'New scene', profile: 'standard' });
        review(result.scene); recoveryStatus('Inspection complete. Review the saved video before starting processing.');
      });
      const discard = async () => { await request(`/api/uploads/${item.upload_id}/discard`, 'POST', {});
        if (receipt?.upload_id === item.upload_id) { receipt = null; byId('discard-video').hidden = true; }
        recoveryStatus('The incomplete local copy and inspection still were removed. The transfer receipt is retained.'); };
      action('Discard incomplete copy', discard);
      action('Discard and restart', async () => { await discard(); selectedScene = null; submissionKey = null;
        onShow();
        byId('video-review').hidden = true; byId('video-playback').pause(); updateReview();
        byId('video-panel').hidden = false; byId('video-file').value = ''; byId('video-file').focus();
        recoveryStatus('The incomplete local copy was discarded. Choose the original file to start a new transfer.'); });
      list.append(card);
    }
    if (!page.uploads.length) list.append(node('p', 'No incomplete transfers on this page.'));
    nextCursor = page.next_cursor; byId('more-transfers').hidden = !nextCursor;
  }
  byId('refresh-transfers').onclick = () => recoverTransfers().catch(report);
  byId('more-transfers').onclick = () => recoverTransfers(nextCursor).catch(report);
  function updateReview() {
    const profile = readiness?.profiles?.[byId('video-profile').value];
    byId('video-resources').textContent = `Expected device: ${byId('video-device').value || profile?.device || 'cpu'}. ${profile?.resource_note || 'Standard defaults to CPU and up to 32 useful images. Selection may retain fewer images.'}`;
    const state = reviewState(selectedScene, readiness);
    byId('start-processing').disabled = !state.canStart;
    byId('start-processing-note').textContent = state.startMessage;
  }
  function review(scene) {
    onShow();
    selectedScene = scene; byId('video-panel').hidden = false; byId('video-review').hidden = false;
    submissionKey = null;
    const inspection = scene.media.inspection;
    byId('video-name').value = scene.name;
    byId('video-profile').value = scene.media.review_settings.profile;
    byId('video-device').value = scene.media.review_settings.device;
    byId('video-preview').src = scene.thumbnail_url;
    byId('video-properties').textContent = `${inspection.duration_seconds.toFixed(2)} seconds · encoded ${inspection.width} × ${inspection.height} · displayed ${inspection.display_width} × ${inspection.display_height} · ${inspection.codec} · ${inspection.preprocessing.color.policy.toUpperCase()} · FFmpeg decode ready`;
    const video = byId('video-playback'); video.hidden = false;
    video.src = `/api/library/scenes/${scene.scene_id}/video`;
    byId('video-playback-note').textContent = 'The inspection still is available whether or not this browser plays the video.';
    video.onerror = () => { video.hidden = true; byId('video-playback-note').textContent = playbackState(true, inspection).message; };
    updateReview(); byId('video-name').focus();
  }
  async function checkSetup() {
    readiness = await request('/api/readiness');
    const preparation = readiness.preparation;
    byId('setup-status').textContent = readiness.processing_ready ? 'The checkpoint, backend, and CPU device are ready. Viewing is available.' : readiness.reasons.map(item => item.message).join(' ');
    if (['preparing', 'downloading', 'complete', 'failed'].includes(preparation.state)) byId('setup-status').textContent += ` ${preparation.message}`;
    byId('prepare-model').disabled = !readiness.backend.installed || ['preparing', 'downloading'].includes(preparation.state) || (readiness.checkpoint.state === 'cached' && readiness.torch_repository.state === 'cached');
    byId('setup-size').textContent = preparation.download_bytes != null ? `Checkpoint download: ${bytes(preparation.download_bytes)}. Missing Torch Hub source adds repository bytes.` : readiness.checkpoint.cached_bytes != null ? `Cached checkpoint: ${bytes(readiness.checkpoint.cached_bytes)}. No checkpoint download is needed.` : 'Download size is unavailable locally. Explicit preparation discovers available byte information before downloading missing files.';
    updateReview();
    if (poll) clearTimeout(poll);
    if (['preparing', 'downloading'].includes(preparation.state) || readiness.devices.cpu == null) poll = setTimeout(() => checkSetup().catch(report), 1500);
  }
  async function sendBytes(file, uploadId) {
    const application = await request('/api/application');
    return new Promise((resolve, reject) => {
      xhr = new XMLHttpRequest(); xhr.open('PUT', `/api/uploads/${uploadId}/content`);
      xhr.setRequestHeader('X-TwinForge-Token', application.request_token);
      xhr.upload.onprogress = event => { byId('video-progress').max = file.size; byId('video-progress').value = event.loaded; byId('video-status').textContent = `Copying ${bytes(event.loaded)} of ${bytes(file.size)} locally.`; };
      xhr.onload = () => { let value; try { value = JSON.parse(xhr.responseText); } catch { reject(new Error('The local transfer response was unavailable. Restart Add video.')); return; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(value); else reject(new Error(value.error?.message || 'The local transfer failed. Restart Add video.')); };
      xhr.onerror = xhr.onabort = () => reject(new Error('The transfer was interrupted. Discard the incomplete local copy and restart Add video.'));
      xhr.send(file);
    });
  }
  byId('add-video').onclick = () => { onShow(); byId('video-panel').hidden = false; byId('video-file').focus(); };
  byId('cancel-video').onclick = () => { if (xhr && xhr.readyState !== 4) xhr.abort(); byId('video-playback').pause(); byId('video-panel').hidden = true; byId('add-video').focus(); };
  byId('video-file').onchange = () => {
    const file = byId('video-file').files[0];
    byId('video-file-info').textContent = file ? `${file.name} · ${bytes(file.size)} · managed local copy · limit ${bytes(readiness?.policy.upload_limit_bytes)}` : 'Choose one supported video.';
  };
  byId('video-form').onsubmit = async event => {
    event.preventDefault(); const file = byId('video-file').files[0]; if (!file) return;
    byId('inspect-video').disabled = true; byId('video-progress').hidden = false; byId('video-review').hidden = true;
    try {
      receipt = await request('/api/uploads', 'POST', { client_name: file.name, expected_bytes: file.size, mime: file.type });
      byId('discard-video').hidden = false;
      await sendBytes(file, receipt.upload_id);
      byId('video-status').textContent = 'Copy complete. Inspecting metadata and one oriented, color-correct still; no neural inference.';
      const result = await request(`/api/uploads/${receipt.upload_id}/complete`, 'POST', { name: file.name.replace(/\.[^.]+$/, '') || 'New scene', profile: 'standard' });
      receipt = null; byId('discard-video').hidden = true;
      byId('video-status').textContent = 'Video is valid and ready for review. The original bytes are preserved.';
      review(result.scene); await refresh(); await checkSetup();
    } catch (error) { byId('video-status').textContent = error.message; }
    finally { byId('inspect-video').disabled = false; byId('video-progress').hidden = true; recoverTransfers().catch(report); }
  };
  byId('discard-video').onclick = async () => {
    if (!receipt) return;
    try { await request(`/api/uploads/${receipt.upload_id}/discard`, 'POST', {}); receipt = null; byId('discard-video').hidden = true; byId('video-status').textContent = 'The incomplete local video copy and inspection still were removed. The transfer receipt is retained.'; await recoverTransfers(); await refresh(); }
    catch (error) { byId('video-status').textContent = error.message; }
  };
  byId('video-review').onsubmit = async event => {
    event.preventDefault(); if (!selectedScene) return;
    try { const scene = await request(`/api/library/scenes/${selectedScene.scene_id}/media/review`, 'POST', { name: byId('video-name').value, profile: byId('video-profile').value, device: byId('video-device').value || null });
      selectedScene = scene; byId('video-status').textContent = 'Scene name and processing settings are saved. Processing has not started.'; await refresh(); updateReview(); }
    catch (error) { byId('video-status').textContent = error.message; }
  };
  byId('video-profile').onchange = () => {
    byId('video-device').value = '';
    byId('video-status').textContent = 'Profile changed. Device uses the profile default; choose an Advanced override if needed.';
    updateReview();
  };
  byId('video-device').onchange = updateReview;
  byId('start-processing').onclick = async () => {
    if (!selectedScene || !start) return;
    byId('start-processing').disabled = true;
    submissionKey ||= crypto.randomUUID();
    try {
      selectedScene = await request(`/api/library/scenes/${selectedScene.scene_id}/media/review`, 'POST', { name: byId('video-name').value, profile: byId('video-profile').value, device: byId('video-device').value || null });
      await start(selectedScene, submissionKey);
      byId('video-panel').hidden = true; byId('video-playback').pause();
    } catch (error) { byId('video-status').textContent = error.message; }
    finally { updateReview(); }
  };
  byId('refresh-setup').onclick = () => checkSetup().catch(report);
  byId('prepare-model').onclick = async () => { byId('prepare-model').disabled = true; try { await request('/api/readiness/prepare', 'POST', {}); await checkSetup(); } catch (error) { report(error); await checkSetup(); } };
  globalThis.addEventListener('pagehide', () => { if (poll) clearTimeout(poll); if (xhr && xhr.readyState !== 4) xhr.abort(); });
  checkSetup().catch(report);
  recoverTransfers().catch(report);
  return { review };
}
