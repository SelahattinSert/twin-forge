// Saved job states survive navigation; no guessed percentage for neural inference.
export const terminalStates = new Set(['ready', 'failed', 'cancelled', 'interrupted']);
export function activityLabel(job) {
  const stage = job.stage.replaceAll('_', ' ');
  const elapsed = Math.floor(job.elapsed_seconds || 0);
  return `${stage} · ${Math.floor(elapsed / 60)}m ${elapsed % 60}s${job.queue_position ? ` · queue position ${job.queue_position}` : ''}${job.selected_images != null ? ` · ${job.selected_images} selected images` : ''}${job.actual_device ? ` · ${job.actual_device}` : ''}`;
}
export function mountActivity({ request, refresh, report, onShow = () => {}, onClose = () => {} }) {
  const list = document.getElementById('activity-list');
  const panel = document.getElementById('activity-panel');
  let timer = null, inFlight = null, stopped = false, refreshPending = false;
  let hasJobSnapshot = false;
  const states = new Map(), cards = new Map();
  const node = (tag, text) => { const result = document.createElement(tag); result.textContent = text; return result; };
  const empty = node('p', 'No processing jobs yet.');
  const ownership = node('p', 'Previous worker ownership is unresolved. New heavy work is blocked.');
  ownership.hidden = true;
  list.replaceChildren(ownership, empty);

  function renderJob(job) {
    let entry = cards.get(job.job_id);
    if (!entry) {
      const card = node('article', ''); card.className = 'activity-card';
      entry = { card, heading: node('h3', ''), stage: node('p', ''), alive: node('p', ''),
        resource: node('p', ''), failure: node('p', ''), actions: node('div', ''),
        details: node('details', ''), history: node('pre', ''), pending: false };
      entry.details.append(node('summary', 'Details'), entry.history);
      card.append(entry.heading, entry.stage, entry.alive, entry.resource, entry.failure,
        entry.actions, entry.details);
      cards.set(job.job_id, entry); list.prepend(card);
    }
    entry.job = job;
    entry.heading.textContent = `${job.scene_name || 'Scene unavailable'} · ${job.settings.label} · run ${job.run_id?.slice(-8) || 'unavailable'} · job ${job.job_id.slice(-8)}`;
    entry.heading.tabIndex = -1;
    entry.stage.textContent = `${job.state.replaceAll('_', ' ')} · ${activityLabel(job)}`;
    entry.alive.hidden = !job.worker_alive;
    entry.alive.textContent = 'Worker is alive. This does not prove mathematical progress.';
    entry.resource.hidden = !job.resource_adjustment?.reason;
    entry.resource.textContent = job.resource_adjustment?.reason
      ? `Views reduced to ${job.resource_adjustment.used_keyframes}: ${job.resource_adjustment.reason}. Fewer images may omit coverage.` : '';
    entry.failure.hidden = !job.failure; entry.failure.textContent = job.failure?.message || '';
    entry.history.textContent = job.events.map(event => `${event.sequence} ${event.timestamp} ${event.message_code} ${JSON.stringify(event.details)}`).join('\n');
    const kind = job.state === 'ready' ? 'open' : terminalStates.has(job.state) ? 'retry' : 'cancel';
    if (entry.kind !== kind) {
      const focused = document.activeElement === entry.action;
      const action = node(kind === 'open' ? 'a' : 'button', '');
      if (kind !== 'open') action.onclick = async () => {
        entry.pending = true; action.disabled = true;
        try {
          await request(`/api/jobs/${job.job_id}/${kind}`, 'POST', kind === 'retry'
            ? { idempotency_key: crypto.randomUUID() } : {});
          await poll();
        } catch (error) { report(error); }
        finally { entry.pending = false; entry.action.disabled = entry.job.state === 'cancelling'; }
      };
      entry.actions.replaceChildren(action); entry.action = action; entry.kind = kind;
      if (focused) action.focus();
    }
    entry.action.textContent = kind === 'open' ? 'Open scene' : kind === 'retry'
      ? 'Retry as new run' : job.state === 'cancelling' ? 'Stopping worker…' : 'Cancel';
    entry.action.disabled = entry.pending || job.state === 'cancelling';
    if (kind === 'open') entry.action.href = job.open_url;
  }

  function poll() {
    if (stopped) return Promise.resolve();
    if (inFlight) return inFlight;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    inFlight = Promise.resolve().then(async () => {
      try {
        const result = await request('/api/jobs');
        if (stopped) return;
        const current = new Set(result.jobs.map(job => job.job_id));
        for (const [id, entry] of cards) if (!current.has(id)) {
          entry.card.remove(); cards.delete(id); states.delete(id);
        }
        for (const job of result.jobs) {
          const known = states.has(job.job_id);
          if ((known && states.get(job.job_id) !== job.state) ||
              (!known && (hasJobSnapshot || job.state === 'ready'))) refreshPending = true;
          states.set(job.job_id, job.state); renderJob(job);
        }
        hasJobSnapshot = true;
        empty.hidden = result.jobs.length > 0; ownership.hidden = !result.ownership_unresolved;
        if (refreshPending) { await refresh(); refreshPending = false; }
      } catch (error) { report(error); }
      finally {
        inFlight = null;
        if (!stopped) timer = setTimeout(() => { timer = null; poll().catch(report); }, 1000);
      }
    });
    return inFlight;
  }
  document.getElementById('show-activity').onclick = () => { onShow(); panel.hidden = false; panel.scrollIntoView(); };
  document.getElementById('close-activity').onclick = () => { panel.hidden = true; onClose(); document.getElementById('scene-list').focus(); };
  globalThis.addEventListener('pagehide', () => { stopped = true; if (timer !== null) clearTimeout(timer); timer = null; });
  poll().catch(report);
  return { async show(jobId) { onShow(); panel.hidden = false; await poll(); const entry = cards.get(jobId);
      if (entry) { entry.card.scrollIntoView(); entry.heading.focus(); } else panel.scrollIntoView(); },
    async start(scene, key) { const job = await request(`/api/library/scenes/${scene.scene_id}/runs`, 'POST', { idempotency_key: key }); onShow(); panel.hidden = false; await poll(); await refresh(); panel.scrollIntoView(); return job; } };
}
