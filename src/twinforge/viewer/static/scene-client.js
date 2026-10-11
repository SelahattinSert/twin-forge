// Shared identity, request and preference contract for the application and legacy viewer.
export function resolveSceneContext(pathname) {
  const match = /^\/scenes\/(scene_[0-9a-f]{32})\/runs\/(run_[0-9a-f]{32})\/sessions\/(session_[0-9a-f]{32})\/?$/.exec(pathname);
  return match ? { sceneId: match[1], runId: match[2], sessionId: match[3],
    apiPrefix: `/api/scenes/${match[1]}/runs/${match[2]}/sessions/${match[3]}` } : null;
}

export const sceneContext = resolveSceneContext(globalThis.location?.pathname || '/');
let requestToken;
export function apiURL(path, context = sceneContext) {
  return context && (path === '/api' || path.startsWith('/api/')) &&
    !/^\/api\/(scenes|library|exports|packages|storage|application)(\/|$)/.test(path)
    ? context.apiPrefix + path.slice(4) : path;
}

export async function sceneFetch(path, options = {}) {
  const app = sceneContext || globalThis.document?.body?.dataset.application === 'library';
  const method = (options.method || 'GET').toUpperCase();
  if (app && !['GET', 'HEAD'].includes(method)) {
    if (!requestToken) {
      const response = await globalThis.fetch('/api/application');
      if (!response.ok) throw new Error('Could not connect to the local application.');
      requestToken = (await response.json()).request_token;
    }
    options = { ...options, headers: { ...options.headers, 'X-TwinForge-Token': requestToken } };
  }
  return globalThis.fetch(apiURL(path), options);
}

export function workspaceURL(record) {
  return `/scenes/${record.scene_id}/runs/${record.default_run_id}/sessions/${record.default_session_id}`;
}

export function saveView(value) {
  if (!sceneContext) return;
  try { sessionStorage.setItem(`twinforge-view:${sceneContext.apiPrefix}`, JSON.stringify(value)); } catch { /* Private browsing may disable storage. */ }
}

export function loadView() {
  if (!sceneContext) return null;
  try { return JSON.parse(sessionStorage.getItem(`twinforge-view:${sceneContext.apiPrefix}`)); } catch { return null; }
}
