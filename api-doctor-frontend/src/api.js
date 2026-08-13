const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const SESSION_STORAGE_KEY = 'api_doctor_session_token';

function getSessionToken() {
  return window.localStorage.getItem(SESSION_STORAGE_KEY) || '';
}

function setSessionToken(token) {
  if (!token) return;
  window.localStorage.setItem(SESSION_STORAGE_KEY, token);
}

function clearSessionToken() {
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

async function request(endpoint, options = {}) {
  const { suppressErrorLog = false, ...fetchOptions } = options;
  const sessionToken = getSessionToken();
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
        ...fetchOptions.headers
      },
      ...fetchOptions
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      const error = new Error(errData.detail || errData.message || `HTTP Error ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return await res.json();
  } catch (err) {
    // `fetch` rejects with a bare TypeError when the dev-server proxy cannot
    // reach the API (backend restarting). Flag it so callers can treat it as a
    // transient outage instead of a real API error.
    if (err instanceof TypeError) {
      err.isNetworkError = true;
    }
    if (!suppressErrorLog && !err.isNetworkError) {
      console.error(`API Error on ${endpoint}:`, err);
    }
    throw err;
  }
}

export const api = {
  getSessionToken,
  setSessionToken,
  clearSessionToken,

  // Auth
  register: async (data) => {
    const res = await request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(data)
    });
    if (res?.session_token) setSessionToken(res.session_token);
    return res;
  },
  login: async (identifier, password) => {
    const res = await request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ identifier, password })
    });
    if (res?.session_token) setSessionToken(res.session_token);
    return res;
  },
  logout: async () => {
    try {
      await request('/api/auth/logout', { method: 'POST', suppressErrorLog: true });
    } finally {
      clearSessionToken();
    }
  },
  getCurrentUser: () => request('/api/auth/me', { suppressErrorLog: true }),
  updateCurrentUser: (data) => request('/api/auth/me', {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  changePassword: (currentPassword, newPassword) => request('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
  }),
  deleteCurrentUser: async () => {
    const res = await request('/api/auth/me', { method: 'DELETE' });
    clearSessionToken();
    return res;
  },

  getHealth: () => request('/health', { suppressErrorLog: true }),

  // Projects / onboarding
  listProjects: () => request('/api/projects', { suppressErrorLog: true }),
  getCurrentProject: () => request('/api/projects/current', { suppressErrorLog: true }),
  getProject: (projectId) => request(`/api/projects/${projectId}`, { suppressErrorLog: true }),
  createProject: (data) => request('/api/projects', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  updateProject: (projectId, data) => request(`/api/projects/${projectId}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  deleteProject: (projectId) => request(`/api/projects/${projectId}`, { method: 'DELETE' }),
  duplicateProject: (projectId, name) => request(`/api/projects/${projectId}/duplicate`, {
    method: 'POST',
    body: JSON.stringify({ name })
  }),
  activateProject: (projectId) => request(`/api/projects/${projectId}/activate`, { method: 'POST' }),
  previewProject: (data) => request('/api/projects/onboarding/preview', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  listGithubRepositories: (token) => request('/api/projects/onboarding/github/repositories', {
    method: 'POST',
    body: JSON.stringify({ token })
  }),
  listGithubBranches: (data) => request('/api/projects/onboarding/github/branches', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  listRenderServices: (apiKey) => request('/api/projects/onboarding/render/services', {
    method: 'POST',
    body: JSON.stringify({ api_key: apiKey })
  }),
  verifyRenderService: (data) => request('/api/projects/onboarding/render/verify', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  verifyGithubIntegration: (projectId) => request(`/api/projects/${projectId}/github/verify`, { method: 'POST' }),
  verifyRenderIntegration: (projectId) => request(`/api/projects/${projectId}/render/verify`, { method: 'POST' }),
  getProjectIntegrations: (projectId) => request(`/api/projects/${projectId}/integrations`, { suppressErrorLog: true }),
  getProjectSettings: (projectId) => request(`/api/projects/${projectId}/settings`, { suppressErrorLog: true }),
  updateProjectSettings: (projectId, data) => request(`/api/projects/${projectId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  getProjectStatus: (projectId) => request(`/api/projects/${projectId}/status`, { suppressErrorLog: true }),
  syncProject: (projectId) => request(`/api/projects/${projectId}/sync`, { method: 'POST' }),
  getProjectFiles: (projectId) => request(`/api/projects/files/list${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),
  getFileContent: (path, projectId) => request(`/api/projects/file-content?path=${encodeURIComponent(path)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}`, { suppressErrorLog: true }),
  connectProject: (data) => request('/api/projects/connect', {
    method: 'POST',
    body: JSON.stringify(data)
  }),

  // Incidents
  listIncidents: (projectId) => request(`/api/incidents${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`, { suppressErrorLog: true }),
  getIncident: (id) => request(`/api/incidents/${id}`),
  getIncidentStatus: (id) => request(`/api/incidents/${id}/status`),
  getIncidentContext: (id) => request(`/api/incidents/${id}/context`, { suppressErrorLog: true }),
  getIncidentDiff: (id) => request(`/api/incidents/${id}/diff`, { suppressErrorLog: true }),
  getIncidentSandbox: (id) => request(`/api/incidents/${id}/sandbox`, { suppressErrorLog: true }),
  getIncidentPR: (id) => request(`/api/incidents/${id}/pr`, { suppressErrorLog: true }),
  ingestIncident: (data) => request('/api/incidents/ingest', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  syncRenderLogs: (serviceId, projectId) => request(`/api/incidents/sync-render${serviceId || projectId ? '?' : ''}${serviceId ? `service_id=${encodeURIComponent(serviceId)}` : ''}${serviceId && projectId ? '&' : ''}${projectId ? `project_id=${encodeURIComponent(projectId)}` : ''}`, {
    method: 'POST'
  }),
  getRenderLogs: (projectId, limit = 200) => request(`/api/incidents/render-logs?limit=${encodeURIComponent(limit)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}`),
  diagnoseIncident: (id) => request(`/api/incidents/${id}/diagnose`, { method: 'POST' }),
  rediagnoseIncident: (id) => request(`/api/incidents/${id}/rediagnose`, { method: 'POST' }),
  triggerDemoScenario: (scenario = 'external_api') => request(`/api/incidents/trigger/${encodeURIComponent(scenario)}`, { method: 'POST' }),
  cancelDiagnosis: (id) => request(`/api/incidents/${id}/cancel`, { method: 'POST' }),
  approveFix: (id, approved = true) => request(`/api/incidents/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved })
  }),
  approveFileRead: (id, approved = true) => request(`/api/incidents/${id}/approve-file-read`, {
    method: 'POST',
    body: JSON.stringify({ approved })
  }),
  approveFixProposal: (id, approved = true) => request(`/api/incidents/${id}/approve-fix`, {
    method: 'POST',
    body: JSON.stringify({ approved })
  }),
  applyFix: (id) => request(`/api/incidents/${id}/apply-fix`, { method: 'POST' }),
  commitFix: (id) => request(`/api/incidents/${id}/commit`, { method: 'POST' }),
  createPR: (id) => request(`/api/incidents/${id}/create-pr`, {
    method: 'POST',
    body: JSON.stringify({ approved: true })
  }),

  // Subscribes to an incident's activity stream and keeps the subscription
  // alive across backend restarts. A dropped connection previously closed the
  // EventSource for good, so the timeline stayed frozen until a full page
  // reload; the stream is now re-established with capped exponential backoff.
  subscribeIncidentStream: (id, onEvent, onError) => {
    let eventSource = null;
    let retryTimer = null;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const token = getSessionToken();
      const url = `${API_BASE}/api/incidents/${id}/stream${token ? `?session_token=${encodeURIComponent(token)}` : ''}`;
      eventSource = new EventSource(url);

      eventSource.onopen = () => {
        attempt = 0;
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onEvent(data);
        } catch (e) {
          console.error('Failed to parse SSE data', e);
        }
      };

      eventSource.onerror = (err) => {
        if (onError) onError(err);
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        if (stopped) return;
        // 1s, 2s, 4s ... capped at 15s so a restarting backend is picked up
        // quickly without hammering it while it is still booting.
        const delay = Math.min(1000 * 2 ** attempt, 15000);
        attempt += 1;
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (eventSource) eventSource.close();
    };
  }
};
