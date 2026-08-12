import React, { useState, useRef, useEffect, useCallback } from 'react';
import TopBar from './components/TopBar';
import ActivityBar from './components/ActivityBar';
import Explorer from './components/Explorer';
import EditorRegion from './components/EditorRegion';
import APIDoctorPanel from './components/APIDoctorPanel';
import BottomPanel from './components/BottomPanel';
import CommandPalette from './components/CommandPalette';
import { api } from './api';
import { 
  GitBranch, 
  GitPullRequest,
  CheckCircle2, 
  Loader2, 
  AlertCircle, 
  X, 
  Server, 
  FileText, 
  Sparkles,
  ArrowRight
} from 'lucide-react';
import './index.css';

const ACTIVE_DIAGNOSIS_STATUSES = new Set([
  'DETECTING',
  'CONTEXT_BUILDING',
  'COLLECTING_CONTEXT',
  'INVESTIGATING',
  'ROOT_CAUSE_IDENTIFIED',
  'ROOT_CAUSE_FOUND',
  'FIX_GENERATING',
  'FIX_PLANNED',
  'SANDBOX_RUNNING',
  'SANDBOX_TESTING',
  'TESTING',
  'VERIFYING',
]);

export default function App() {
  // Backend & Project States
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);
  const [currentProject, setCurrentProject] = useState(null);
  const [projectFiles, setProjectFiles] = useState({ files: [], tree: [] });
  const [selectedFile, setSelectedFile] = useState('');
  const [fileContent, setFileContent] = useState('');

  // Incidents
  const [incidentsList, setIncidentsList] = useState([]);
  const [activeIncidentId, setActiveIncidentId] = useState(null);
  const [activeIncident, setActiveIncident] = useState(null);
  const [incidentContext, setIncidentContext] = useState(null);
  const [incidentDiff, setIncidentDiff] = useState(null);
  const [incidentSandbox, setIncidentSandbox] = useState(null);
  const [incidentPR, setIncidentPR] = useState(null);
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [isDiagnosing, setIsDiagnosing] = useState(false);

  // Modals & First Run
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [showIngestModal, setShowIngestModal] = useState(false);
  const [connectForm, setConnectForm] = useState({
    github_owner: '',
    github_repo: '',
    github_branch: 'main',
    render_service_id: '',
    github_token: ''
  });
  const [connectProgress, setConnectProgress] = useState(null); // null | 'connecting' | 'done' | 'error'
  const [connectSteps, setConnectSteps] = useState([]);
  const [connectError, setConnectError] = useState('');

  // Ingest Modal Form
  const [ingestForm, setIngestForm] = useState({
    source: 'manual',
    message: '',
    log_text: '',
    endpoint: '',
    method: 'GET'
  });
  const [isIngesting, setIsIngesting] = useState(false);

  // Layout & Visibility
  const [activeBottomTab, setActiveBottomTab] = useState('terminal');
  const [isExplorerOpen, setIsExplorerOpen] = useState(true);
  const [isDoctorOpen, setIsDoctorOpen] = useState(true);
  const [isBottomCollapsed, setIsBottomCollapsed] = useState(false);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // Resizable widths
  const [explorerWidth, setExplorerWidth] = useState(240);
  const [doctorWidth, setDoctorWidth] = useState(380);
  const [bottomHeight, setBottomHeight] = useState(220);

  // Highlight line & failure info
  const [highlightLine, setHighlightLine] = useState(null);
  const [failureReason, setFailureReason] = useState('');

  // 1. Initial State & Project Loading
  const refreshBackendState = useCallback(async () => {
    try {
      const health = await api.getHealth();
      setBackendHealth(health);
      setIsBackendConnected(health.status === 'ok');

      // Fetch current project
      try {
        const proj = await api.getCurrentProject();
        setCurrentProject(proj);
      } catch (e) {
        console.warn('Could not fetch project:', e);
      }

      // Fetch incidents
      const incidents = await api.listIncidents();
      setIncidentsList(incidents || []);
      
      if (!activeIncidentId && incidents && incidents.length > 0) {
        setActiveIncidentId(incidents[0].id);
      }
    } catch (err) {
      console.error('Failed to refresh backend state:', err);
      setIsBackendConnected(false);
      setBackendHealth(null);
    }
  }, [activeIncidentId]);

  useEffect(() => {
    refreshBackendState();
    const interval = setInterval(refreshBackendState, 6000);
    return () => clearInterval(interval);
  }, [refreshBackendState]);

  // 2. Load Workspace Files when Project is Connected
  const loadProjectFiles = useCallback(async () => {
    try {
      const res = await api.getProjectFiles();
      if (res && res.files) {
        setProjectFiles({ files: res.files, tree: res.tree || [] });
        // Set initial selected file if not selected yet
        if (!selectedFile && res.files.length > 0) {
          const defaultFile = res.files.find(f => f.toLowerCase().includes('main') || f.toLowerCase().includes('index') || f.toLowerCase().includes('readme')) || res.files[0];
          setSelectedFile(defaultFile);
        }
      }
    } catch (err) {
      console.warn('Failed to load project files:', err);
    }
  }, [selectedFile]);

  useEffect(() => {
    if (currentProject) {
      loadProjectFiles();
    }
  }, [currentProject, loadProjectFiles]);

  // 3. Load File Content when selectedFile changes
  useEffect(() => {
    if (!selectedFile) return;
    let isMounted = true;
    api.getFileContent(selectedFile)
      .then(res => {
        if (isMounted && res && res.content !== undefined) {
          setFileContent(res.content);
        }
      })
      .catch(err => {
        console.warn(`Could not read ${selectedFile}:`, err);
        if (isMounted) setFileContent('');
      });
    return () => { isMounted = false; };
  }, [selectedFile]);

  // 4. Fetch full incident details when activeIncidentId changes
  const fetchIncidentDetails = useCallback(async (id) => {
    if (!id) return;
    try {
      const [inc, ctx, diff, sb, pr] = await Promise.allSettled([
        api.getIncident(id),
        api.getIncidentContext(id),
        api.getIncidentDiff(id),
        api.getIncidentSandbox(id),
        api.getIncidentPR(id)
      ]);

      if (inc.status === 'fulfilled') {
        const incData = inc.value;
        setActiveIncident(incData);
        setIsDiagnosing(ACTIVE_DIAGNOSIS_STATUSES.has(incData.status));

        // Auto-navigate to implicated file and line
        const rc = incData.root_cause;
        if (rc && rc.affected_files && rc.affected_files.length > 0) {
          setSelectedFile(rc.affected_files[0]);
          if (rc.affected_lines && rc.affected_lines.length > 0) {
            setHighlightLine(rc.affected_lines[0]);
          }
          if (rc.root_cause) {
            setFailureReason(rc.root_cause);
          }
        }
      }
      if (ctx.status === 'fulfilled') {
        setIncidentContext(ctx.value);
        if (ctx.value.implicated_files && ctx.value.implicated_files.length > 0 && !selectedFile) {
          setSelectedFile(ctx.value.implicated_files[0]);
        }
      }
      if (diff.status === 'fulfilled') setIncidentDiff(diff.value);
      if (sb.status === 'fulfilled') setIncidentSandbox(sb.value);
      if (pr.status === 'fulfilled') setIncidentPR(pr.value);
    } catch (err) {
      console.error('Failed to fetch incident details:', err);
    }
  }, [selectedFile]);

  useEffect(() => {
    if (activeIncidentId) {
      fetchIncidentDetails(activeIncidentId);
    }
  }, [activeIncidentId, fetchIncidentDetails]);

  // 5. Real-time SSE Stream subscription
  useEffect(() => {
    if (!activeIncidentId) return;
    setTimelineEvents([]);

    const unsubscribe = api.subscribeIncidentStream(
      activeIncidentId,
      (eventData) => {
        if (eventData.step || eventData.message) {
          setTimelineEvents(prev => [...prev, eventData]);
        }
        fetchIncidentDetails(activeIncidentId);
      },
      () => console.log('SSE stream closed')
    );

    return () => unsubscribe();
  }, [activeIncidentId, fetchIncidentDetails]);

  // 6. Project Connection Workflow
  const handleConnectRepository = async (e) => {
    if (e) e.preventDefault();
    if (!connectForm.github_owner || !connectForm.github_repo) {
      alert('GitHub Owner and Repository are required.');
      return;
    }

    setConnectProgress('connecting');
    setConnectError('');
    setConnectSteps([]);

    try {
      setConnectSteps(['Validating GitHub configuration...']);
      const res = await api.connectProject(connectForm);
      if (res && res.project) {
        setCurrentProject(res.project);
        setConnectSteps(res.steps_completed || [
          'github_connected',
          'repository_verified',
          'repository_synchronized',
          'project_discovered'
        ]);
        setConnectProgress('done');
        await loadProjectFiles();
        setTimeout(() => {
          setShowConnectModal(false);
          setConnectProgress(null);
        }, 1200);
      }
    } catch (err) {
      setConnectProgress('error');
      setConnectError(err.message || 'Failed to connect repository.');
    }
  };

  // 7. Manual Error Ingestion Workflow
  const handleIngestIncident = async (e) => {
    if (e) e.preventDefault();
    if (!ingestForm.log_text && !ingestForm.message) {
      alert('Please enter log text or an error message.');
      return;
    }

    setIsIngesting(true);
    try {
      const res = await api.ingestIncident({
        ...ingestForm,
        raw_logs: ingestForm.log_text,
        stack_trace: ingestForm.log_text,
        auto_diagnose: true
      });
      if (res && res.incident_id) {
        setActiveIncidentId(res.incident_id);
        setShowIngestModal(false);
        setIsDiagnosing(true);
        setIngestForm({ source: 'manual', message: '', log_text: '', endpoint: '', method: 'GET' });
        await refreshBackendState();
        fetchIncidentDetails(res.incident_id);
      }
    } catch (err) {
      alert(`Ingestion failed: ${err.message}`);
    } finally {
      setIsIngesting(false);
    }
  };

  // 8. Sync Render Logs Workflow
  const handleSyncRender = async () => {
    try {
      const res = await api.syncRenderLogs();
      if (res.status === 'unconfigured') {
        alert('Render integration is not configured. Set RENDER_API_KEY and RENDER_SERVICE_ID in .env or settings.');
        return;
      }
      if (res.incidents_created && res.incidents_created.length > 0) {
        setActiveIncidentId(res.incidents_created[0]);
        await refreshBackendState();
        fetchIncidentDetails(res.incidents_created[0]);
      } else {
        alert(res.message || 'Render logs synced: no new errors detected.');
      }
    } catch (err) {
      alert(`Failed to sync Render logs: ${err.message}`);
    }
  };

  // 9. Start/Stop Diagnosis Handlers
  const handleStartDiagnosis = async () => {
    if (activeIncidentId) {
      try {
        setIsDiagnosing(true);
        await api.diagnoseIncident(activeIncidentId);
        await fetchIncidentDetails(activeIncidentId);
      } catch (err) {
        alert(`Diagnosis failed: ${err.message}`);
        setIsDiagnosing(false);
      }
    } else {
      setShowIngestModal(true);
    }
  };

  const handleStopDiagnosis = async () => {
    if (!activeIncidentId) return;
    try {
      await api.cancelDiagnosis(activeIncidentId);
      setIsDiagnosing(false);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to stop diagnosis: ${err.message}`);
    }
  };

  const handleApproveFix = async (approved) => {
    if (!activeIncidentId) return;
    try {
      await api.approveFix(activeIncidentId, approved);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to record approval: ${err.message}`);
    }
  };

  const handleCreatePR = async () => {
    if (!activeIncidentId) return;
    try {
      await api.createPR(activeIncidentId);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to create GitHub PR: ${err.message}`);
    }
  };

  // Resizable drag handles
  const isDraggingExplorer = useRef(false);
  const isDraggingDoctor = useRef(false);
  const isDraggingBottom = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDraggingExplorer.current) {
        setExplorerWidth(Math.min(Math.max(e.clientX - 48, 160), 450));
      } else if (isDraggingDoctor.current) {
        setDoctorWidth(Math.min(Math.max(window.innerWidth - e.clientX, 280), 550));
      } else if (isDraggingBottom.current) {
        setBottomHeight(Math.min(Math.max(window.innerHeight - e.clientY, 80), 500));
      }
    };

    const handleMouseUp = () => {
      isDraggingExplorer.current = false;
      isDraggingDoctor.current = false;
      isDraggingBottom.current = false;
      document.body.style.cursor = 'default';
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const isConnected = Boolean(currentProject?.is_connected || (currentProject?.github_owner && currentProject?.github_repo));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Top Bar */}
      <TopBar 
        activeIncident={activeIncident}
        onStartDiagnosis={handleStartDiagnosis}
        onStopDiagnosis={handleStopDiagnosis}
        onSyncRender={handleSyncRender}
        onOpenIngestModal={() => setShowIngestModal(true)}
        onOpenConnectModal={() => setShowConnectModal(true)}
        isDiagnosing={isDiagnosing}
        isBackendConnected={isBackendConnected}
        backendHealth={backendHealth}
        currentProject={currentProject}
      />

      {/* Main Workspace Canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        
        {/* Upper Region */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', width: '100%' }}>
          
          <ActivityBar 
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            isExplorerOpen={isExplorerOpen}
            setIsExplorerOpen={setIsExplorerOpen}
            hasActiveIncident={Boolean(activeIncident)}
          />

          <Explorer 
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            fileStatuses={{
              ...Object.fromEntries(
                (incidentContext?.implicated_files || []).map(path => [path, isDiagnosing ? 'reading' : 'analyzed'])
              ),
              ...Object.fromEntries(
                (incidentDiff?.files_changed || []).map(path => [path, 'modified'])
              )
            }}
            filesList={projectFiles.files}
            filesTree={projectFiles.tree}
            projectName={currentProject?.name || 'Workspace'}
            onRefresh={loadProjectFiles}
            explorerWidth={explorerWidth}
            isExplorerOpen={isExplorerOpen}
          />

          {isExplorerOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={() => {
                isDraggingExplorer.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          <EditorRegion 
            selectedFile={selectedFile}
            fileContent={fileContent}
            incidentContext={incidentContext}
            incidentDiff={incidentDiff}
            isDiagnosing={isDiagnosing}
            isDiffMode={isDiffMode}
            setIsDiffMode={setIsDiffMode}
            onApproveFix={handleApproveFix}
            highlightLine={highlightLine}
            failureReason={failureReason}
          />

          {isDoctorOpen && (
            <div 
              className="resize-handle-col"
              onMouseDown={() => {
                isDraggingDoctor.current = true;
                document.body.style.cursor = 'col-resize';
              }}
            />
          )}

          <APIDoctorPanel 
            incidentsList={incidentsList}
            activeIncident={activeIncident}
            incidentContext={incidentContext}
            incidentDiff={incidentDiff}
            incidentSandbox={incidentSandbox}
            incidentPR={incidentPR}
            timelineEvents={timelineEvents}
            isDiagnosing={isDiagnosing}
            onStartDiagnosis={handleStartDiagnosis}
            onApproveFix={handleApproveFix}
            onCreatePR={handleCreatePR}
            onSelectIncident={(id) => setActiveIncidentId(id)}
            onSyncRender={handleSyncRender}
            onOpenIngestModal={() => setShowIngestModal(true)}
            doctorWidth={doctorWidth}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            setSelectedFile={setSelectedFile}
            setIsDiffMode={setIsDiffMode}
          />
        </div>

        {!isBottomCollapsed && (
          <div 
            className="resize-handle-row"
            onMouseDown={() => {
              isDraggingBottom.current = true;
              document.body.style.cursor = 'row-resize';
            }}
          />
        )}

        <BottomPanel 
          activeIncident={activeIncident}
          incidentContext={incidentContext}
          incidentDiff={incidentDiff}
          incidentSandbox={incidentSandbox}
          activeBottomTab={activeBottomTab}
          setActiveBottomTab={setActiveBottomTab}
          bottomHeight={bottomHeight}
          isBottomCollapsed={isBottomCollapsed}
          setIsBottomCollapsed={setIsBottomCollapsed}
        />
      </div>

      {/* FIRST RUN / CONNECT REPOSITORY MODAL */}
      {(showConnectModal || (!isConnected && !currentProject?.github_owner)) && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.75)',
          backdropFilter: 'blur(3px)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div style={{
            backgroundColor: 'var(--surface-1)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '24px',
            width: '460px',
            boxShadow: '0 16px 40px rgba(0,0,0,0.6)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <GitBranch size={20} style={{ color: 'var(--color-accent)' }} />
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Connect a GitHub repository to begin
                </h3>
              </div>
              {isConnected && (
                <button onClick={() => setShowConnectModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                  <X size={16} />
                </button>
              )}
            </div>

            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '20px', lineHeight: 1.5 }}>
              API Doctor synchronizes the repository into an isolated local baseline, analyzes project architecture, and verifies patches without touching main.
            </p>

            <form onSubmit={handleConnectRepository} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Repository Owner:
                </label>
                <input 
                  type="text"
                  placeholder="e.g. dushu2006 or octocat"
                  value={connectForm.github_owner}
                  onChange={e => setConnectForm({ ...connectForm, github_owner: e.target.value })}
                  required
                  style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', outline: 'none', fontFamily: 'var(--font-mono)' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Repository Name:
                </label>
                <input 
                  type="text"
                  placeholder="e.g. API-DOCTOR or my-backend"
                  value={connectForm.github_repo}
                  onChange={e => setConnectForm({ ...connectForm, github_repo: e.target.value })}
                  required
                  style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', outline: 'none', fontFamily: 'var(--font-mono)' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Branch:
                </label>
                <input 
                  type="text"
                  placeholder="main"
                  value={connectForm.github_branch}
                  onChange={e => setConnectForm({ ...connectForm, github_branch: e.target.value })}
                  style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', outline: 'none', fontFamily: 'var(--font-mono)' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Render Service ID (Optional):
                </label>
                <input 
                  type="text"
                  placeholder="e.g. srv-c..."
                  value={connectForm.render_service_id}
                  onChange={e => setConnectForm({ ...connectForm, render_service_id: e.target.value })}
                  style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', outline: 'none', fontFamily: 'var(--font-mono)' }}
                />
              </div>

              {/* Progress Checklist */}
              {connectProgress && (
                <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px', marginTop: '6px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: connectSteps.includes('github_connected') ? 'var(--color-success)' : 'var(--text-muted)' }}>
                      {connectSteps.includes('github_connected') ? <CheckCircle2 size={14} /> : <Loader2 size={14} className="spin" />}
                      <span>GitHub connected</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: connectSteps.includes('repository_verified') ? 'var(--color-success)' : 'var(--text-muted)' }}>
                      {connectSteps.includes('repository_verified') ? <CheckCircle2 size={14} /> : <span style={{ width: '14px' }} />}
                      <span>Repository verified</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: connectSteps.includes('repository_synchronized') ? 'var(--color-success)' : 'var(--text-muted)' }}>
                      {connectSteps.includes('repository_synchronized') ? <CheckCircle2 size={14} /> : <span style={{ width: '14px' }} />}
                      <span>Repository synchronized</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: connectSteps.includes('project_discovered') ? 'var(--color-success)' : 'var(--text-muted)' }}>
                      {connectSteps.includes('project_discovered') ? <CheckCircle2 size={14} /> : <span style={{ width: '14px' }} />}
                      <span>Project discovered</span>
                    </div>
                  </div>
                  {connectError && (
                    <div style={{ color: 'var(--color-failure)', fontSize: '11px', marginTop: '8px' }}>
                      {connectError}
                    </div>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
                {isConnected && (
                  <button type="button" onClick={() => setShowConnectModal(false)} className="btn-outline">
                    Cancel
                  </button>
                )}
                <button 
                  type="submit" 
                  disabled={connectProgress === 'connecting'} 
                  className="btn-primary" 
                  style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  {connectProgress === 'connecting' ? <Loader2 size={14} className="spin" /> : <ArrowRight size={14} />}
                  <span>Connect Repository</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* INGEST PRODUCTION LOG / ERROR MODAL */}
      {showIngestModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.7)',
          backdropFilter: 'blur(3px)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div style={{
            backgroundColor: 'var(--surface-1)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '24px',
            width: '560px',
            boxShadow: '0 16px 40px rgba(0,0,0,0.6)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={18} style={{ color: 'var(--color-accent)' }} />
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Ingest Production Failure or Stack Trace
                </h3>
              </div>
              <button onClick={() => setShowIngestModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Paste runtime logs or an error traceback. API Doctor will parse the stack trace, retrieve the implicated repository source, and begin investigation.
            </p>

            <form onSubmit={handleIngestIncident} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Source:
                  </label>
                  <select 
                    value={ingestForm.source}
                    onChange={e => setIngestForm({ ...ingestForm, source: e.target.value })}
                    style={{ width: '100%', padding: '6px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px' }}
                  >
                    <option value="render">Render Runtime</option>
                    <option value="github_actions">GitHub Actions / CI</option>
                    <option value="manual">Manual Error Log</option>
                  </select>
                </div>
                <div style={{ flex: 2 }}>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Endpoint / Route (Optional):
                  </label>
                  <input 
                    type="text"
                    placeholder="e.g. POST /api/v1/checkout"
                    value={ingestForm.endpoint}
                    onChange={e => setIngestForm({ ...ingestForm, endpoint: e.target.value })}
                    style={{ width: '100%', padding: '6px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Raw Log / Stack Trace:
                </label>
                <textarea 
                  rows={8}
                  placeholder={`Traceback (most recent call last):\n  File "app/services/payment.py", line 121, in charge_user\n    token = user.payment_method.token\nAttributeError: 'NoneType' object has no attribute 'token'`}
                  value={ingestForm.log_text}
                  onChange={e => setIngestForm({ ...ingestForm, log_text: e.target.value })}
                  required
                  style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '11px', fontFamily: 'var(--font-mono)', outline: 'none', resize: 'vertical' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '6px' }}>
                <button type="button" onClick={() => setShowIngestModal(false)} className="btn-outline">
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={isIngesting} 
                  className="btn-primary" 
                  style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  {isIngesting ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  <span>Ingest & Start Diagnosis</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Command Palette (⌘K) */}
      <CommandPalette 
        isOpen={isCommandPaletteOpen}
        onClose={(val) => setIsCommandPaletteOpen(typeof val === 'boolean' ? val : false)}
        setCurrentState={() => handleStartDiagnosis()}
        setIsDiffMode={setIsDiffMode}
        setActiveBottomTab={setActiveBottomTab}
      />
    </div>
  );
}
