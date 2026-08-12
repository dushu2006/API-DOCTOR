// Empty by default so browser requests stay same-origin. The Vite dev server
// proxies them to the backend; deployments can set VITE_API_BASE_URL when the
// API is hosted on a separate origin.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

async function request(endpoint, options = {}) {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.message || `HTTP Error ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

export const api = {
  getHealth: () => request('/health'),

  // Project workspace management
  getCurrentProject: () => request('/api/projects/current'),
  listProjects: () => request('/api/projects'),
  connectProject: (data) => request('/api/projects/connect', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  syncProject: () => request('/api/projects/sync', { method: 'POST' }),
  getProjectFiles: (projectId = 'default') => request(`/api/projects/files/list?project_id=${projectId}`),
  getFileContent: (path, projectId = 'default') => request(`/api/projects/file-content?path=${encodeURIComponent(path)}&project_id=${projectId}`),

  // Incident lifecycle & ingestion
  listIncidents: (projectId) => request(`/api/incidents${projectId ? `?project_id=${projectId}` : ''}`),
  getIncident: (id) => request(`/api/incidents/${id}`),
  getIncidentStatus: (id) => request(`/api/incidents/${id}/status`),
  getIncidentContext: (id) => request(`/api/incidents/${id}/context`),
  getIncidentDiff: (id) => request(`/api/incidents/${id}/diff`),
  getIncidentSandbox: (id) => request(`/api/incidents/${id}/sandbox`),
  getIncidentPR: (id) => request(`/api/incidents/${id}/pr`),

  ingestIncident: (data) => request('/api/incidents/ingest', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  syncRenderLogs: (serviceId) => request(`/api/incidents/sync-render${serviceId ? `?service_id=${serviceId}` : ''}`, {
    method: 'POST'
  }),
  triggerScenario: (scenario = 'null_pointer') => request(`/api/incidents/trigger/${scenario}`, { method: 'POST' }),
  diagnoseIncident: (id) => request(`/api/incidents/${id}/diagnose`, { method: 'POST' }),
  cancelDiagnosis: (id) => request(`/api/incidents/${id}/cancel`, { method: 'POST' }),
  approveFix: (id, approved = true) => request(`/api/incidents/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved })
  }),
  createPR: (id) => request(`/api/incidents/${id}/create-pr`, {
    method: 'POST',
    body: JSON.stringify({ approved: true })
  }),

  subscribeIncidentStream: (id, onEvent, onError) => {
    const url = `${API_BASE}/api/incidents/${id}/stream`;
    const eventSource = new EventSource(url);
    
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
      eventSource.close();
    };

    return () => eventSource.close();
  }
};
