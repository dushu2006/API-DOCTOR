const API_BASE = 'http://localhost:8000';

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
      throw new Error(errData.detail || `HTTP Error ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

export const api = {
  getHealth: () => request('/health'),
  listIncidents: (projectId) => request(`/api/incidents${projectId ? `?project_id=${projectId}` : ''}`),
  getIncident: (id) => request(`/api/incidents/${id}`),
  getIncidentStatus: (id) => request(`/api/incidents/${id}/status`),
  getIncidentContext: (id) => request(`/api/incidents/${id}/context`),
  getIncidentDiff: (id) => request(`/api/incidents/${id}/diff`),
  getIncidentSandbox: (id) => request(`/api/incidents/${id}/sandbox`),
  getIncidentPR: (id) => request(`/api/incidents/${id}/pr`),
  
  triggerScenario: (scenario = 'null_pointer') => request(`/api/incidents/trigger/${scenario}`, { method: 'POST' }),
  diagnoseIncident: (id) => request(`/api/incidents/${id}/diagnose`, { method: 'POST' }),
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
