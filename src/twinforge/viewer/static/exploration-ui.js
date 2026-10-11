import { fullClipRanges, validView, ViewStore, viewStorageKey } from '/view-state.js';
import { canvasPNG, downloadBlob } from '/scene-snapshot.js';

export class ExplorationUI {
  constructor(byId, callbacks) {
    this.byId = byId; this.callbacks = callbacks; this.ranges = fullClipRanges(); this.enabled = false;
    this.pendingClip = null; this.captureGeneration = 0;
    this.bindViews(); this.bindClip(); this.bindScreenshot();
  }
  setScene(metadata, identity, variant) {
    this.captureGeneration++; this.closeScreenshot();
    // Changing scale/copy invalidates viewing-space crop bounds. Never transfer
    // absolute camera coordinates to another artifact implicitly.
    this.ranges = fullClipRanges(); this.enabled = false; this.syncClip();
    try { this.store = new ViewStore(globalThis.localStorage, viewStorageKey(metadata, identity, variant)); this.refreshViews(); }
    catch { this.store = null; this.byId('saved-views').replaceChildren(); this.syncViewButtons(); this.viewMessage('Saved views could not be loaded. Browser storage is unavailable or its saved data is invalid.'); }
  }
  viewMessage(text) { this.byId('saved-view-status').textContent = text; }
  refreshViews(selected = '') {
    const items = this.store.list(), select = this.byId('saved-views'); select.replaceChildren();
    select.append(new Option(items.length ? 'Choose a saved view' : 'No saved views yet', ''));
    for (const item of items) select.append(new Option(item.name, item.id));
    select.value = selected; this.syncViewButtons();
    this.viewMessage(`${items.length} / 20 views saved in this browser. Camera and clip settings only; point filters are not saved.`);
  }
  syncViewButtons() {
    const selected = Boolean(this.byId('saved-views').value);
    for (const id of ['open-saved-view', 'rename-saved-view', 'delete-saved-view']) this.byId(id).disabled = !selected;
  }
  bindViews() {
    const run = action => { try { if (!this.store) throw new Error('Browser storage is unavailable.'); action(); } catch (error) { this.viewMessage(`Could not update saved views: ${error.message}`); } };
    this.byId('save-view').onclick = () => run(() => {
      const id = this.store.add(this.byId('saved-view-name').value, this.callbacks.captureView(), crypto.randomUUID());
      this.refreshViews(id); this.viewMessage('View saved in this browser. Reconstruction files are unchanged.');
    });
    this.byId('saved-views').onchange = () => run(() => {
      this.syncViewButtons();
      const item = this.store.list().find(item => item.id === this.byId('saved-views').value);
      if (item) this.byId('saved-view-name').value = item.name;
    });
    this.byId('open-saved-view').onclick = () => run(() => {
      const item = this.store.list().find(item => item.id === this.byId('saved-views').value);
      if (!item || !validView(item.view)) throw new Error('Choose a valid saved view.');
      this.callbacks.restoreView(item.view);
      this.enabled = item.view.clipEnabled; this.ranges = item.view.clipRanges.map(pair => [...pair]); this.syncClip();
      this.viewMessage(`Opened ${item.name}. Current point filters are unchanged.`);
    });
    this.byId('rename-saved-view').onclick = () => run(() => {
      const id = this.byId('saved-views').value; this.store.rename(id, this.byId('saved-view-name').value); this.refreshViews(id);
    });
    this.byId('delete-saved-view').onclick = () => run(() => {
      this.store.remove(this.byId('saved-views').value); this.refreshViews();
    });
  }
  bindClip() {
    this.byId('clip-enabled').onchange = event => { this.enabled = event.target.checked; this.syncClip(); };
    for (const [index, axis] of ['x', 'y', 'z'].entries()) {
      for (const [side, suffix] of ['min', 'max'].entries()) {
        this.byId(`clip-${axis}-${suffix}`).oninput = event => {
          const number = Number(event.target.value); if (!Number.isFinite(number)) return;
          this.ranges[index][side] = Math.min(100, Math.max(0, Math.round(number)));
          if (side === 0) this.ranges[index][0] = Math.min(this.ranges[index][0], this.ranges[index][1] - 1);
          else this.ranges[index][1] = Math.max(this.ranges[index][1], this.ranges[index][0] + 1);
          // Slider changes are coalesced to one geometry-index update per frame.
          this.syncClip(false); cancelAnimationFrame(this.pendingClip);
          this.pendingClip = requestAnimationFrame(() => { this.pendingClip = null; this.callbacks.clipChanged(); });
        };
      }
    }
    this.byId('clip-reset').onclick = () => { this.ranges = fullClipRanges(); this.enabled = false; this.syncClip(); };
  }
  syncClip(notify = true) {
    if (notify) { cancelAnimationFrame(this.pendingClip); this.pendingClip = null; }
    this.byId('clip-enabled').checked = this.enabled;
    for (const [index, axis] of ['x', 'y', 'z'].entries()) for (const [side, suffix] of ['min', 'max'].entries()) {
      const input = this.byId(`clip-${axis}-${suffix}`); input.value = this.ranges[index][side]; input.disabled = !this.enabled;
      this.byId(`clip-${axis}-${suffix}-value`).textContent = `${this.ranges[index][side]}%`;
    }
    this.byId('clip-status').textContent = this.enabled ? 'Viewing cutaway active. Outside points and overlays are hidden, not deleted. Geometry exports remain complete.' : 'Full viewing volume. No clip box is active.';
    if (notify) this.callbacks.clipChanged();
  }
  bindScreenshot() {
    const dialog = this.byId('snapshot-dialog');
    this.byId('capture-view').onclick = () => {
      this.snapshotReturnFocus = document.activeElement;
      this.byId('snapshot-title').value = 'TwinForge scene view'; this.byId('snapshot-note').value = '';
      this.byId('snapshot-download').disabled = false;
      this.byId('snapshot-status').textContent = 'The PNG includes scene identity, scale status, visibility context and your note.';
      dialog.showModal(); this.byId('snapshot-title').focus();
    };
    this.byId('snapshot-cancel').onclick = () => this.closeScreenshot();
    dialog.addEventListener('cancel', event => { event.preventDefault(); this.closeScreenshot(); });
    dialog.addEventListener('close', () => { this.captureGeneration++; this.snapshotReturnFocus?.focus(); });
    this.byId('snapshot-download').onclick = async () => {
      const generation = ++this.captureGeneration;
      const button = this.byId('snapshot-download'); button.disabled = true;
      try {
        const canvas = this.callbacks.screenshot(this.byId('snapshot-title').value, this.byId('snapshot-note').value);
        const blob = await canvasPNG(canvas);
        if (generation !== this.captureGeneration || !dialog.open) return;
        downloadBlob(blob, `twinforge-view-${new Date().toISOString().replace(/[:.]/g, '-')}.png`);
        this.byId('snapshot-status').textContent = 'PNG download requested. Source geometry and measurements are unchanged.';
      } catch (error) { if (generation === this.captureGeneration) this.byId('snapshot-status').textContent = `Could not capture this view: ${error.message}`; }
      finally { if (generation === this.captureGeneration) button.disabled = false; }
    };
  }
  closeScreenshot() { this.captureGeneration++; if (this.byId('snapshot-dialog').open) this.byId('snapshot-dialog').close(); }
  dispose() { cancelAnimationFrame(this.pendingClip); this.closeScreenshot(); }
}
