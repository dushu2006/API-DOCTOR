import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import TopBar from './components/TopBar';
import ActivityBar from './components/ActivityBar';
import Explorer from './components/Explorer';
import EditorRegion from './components/EditorRegion';
import APIDoctorPanel from './components/APIDoctorPanel';
import BottomPanel from './components/BottomPanel';
import CommandPalette from './components/CommandPalette';
import ProjectSetupWizard from './components/ProjectSetupWizard';
import ProjectSelectorModal from './components/ProjectSelectorModal';
import LoginPage from './components/LoginPage';
import ProfileModal from './components/ProfileModal';
import ProjectSettingsModal from './components/ProjectSettingsModal';
import { api } from './api';
import { FileText, Loader2, Server, Sparkles, X } from 'lucide-react';
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
  // Interactive workflow pause points (still active, waiting for user)
  'AWAITING_FILE_READ_APPROVAL',
  'AWAITING_FIX_APPROVAL',
]);

export default function App() {
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [projects, setProjects] = useState([]);
  const [currentProject, setCurrentProject] = useState(null);
  const [showProjectWizard, setShowProjectWizard] = useState(false);
  const [showProjectSelector, setShowProjectSelector] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showProjectSettings, setShowProjectSettings] = useState(false);
  const selectedProjectOnce = useRef(false);

  const [projectFiles, setProjectFiles] = useState({ files: [], tree: [] });
  const [selectedFile, setSelectedFile] = useState('');
  const [fileContent, setFileContent] = useState('');

  const [incidentsList, setIncidentsList] = useState([]);
  const [activeIncidentId, setActiveIncidentId] = useState(null);
  const [activeIncident, setActiveIncident] = useState(null);
  const [incidentContext, setIncidentContext] = useState(null);
  const [incidentDiff, setIncidentDiff] = useState(null);
  const [incidentSandbox, setIncidentSandbox] = useState(null);
  const [incidentPR, setIncidentPR] = useState(null);
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [isDiagnosing, setIsDiagnosing] = useState(false);
  const [renderLogs, setRenderLogs] = useState([]);
  const [renderLogsMeta, setRenderLogsMeta] = useState(null);

  const [showIngestModal, setShowIngestModal] = useState(false);
  const [ingestForm, setIngestForm] = useState({
    source: 'manual',
    message: '',
    log_text: '',
    endpoint: '',
    method: 'GET'
  });
  const [isIngesting, setIsIngesting] = useState(false);

  const [activeBottomTab, setActiveBottomTab] = useState('terminal');
  const [isExplorerOpen, setIsExplorerOpen] = useState(true);
  const [isDoctorOpen, setIsDoctorOpen] = useState(true);
  const [isBottomCollapsed, setIsBottomCollapsed] = useState(false);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const [explorerWidth, setExplorerWidth] = useState(240);
  const [doctorWidth, setDoctorWidth] = useState(380);
  const [bottomHeight, setBottomHeight] = useState(220);

  const [highlightLine, setHighlightLine] = useState(null);
  const [failureReason, setFailureReason] = useState('');
  const [fileContentVersion, setFileContentVersion] = useState(0);

  // Ref mirror so the SSE subscription does not depend on the selected file.
  const selectedFileRef = useRef('');
  useEffect(() => { selectedFileRef.current = selectedFile; }, [selectedFile]);

  const isDraggingExplorer = useRef(false);
  const isDraggingDoctor = useRef(false);
  const isDraggingBottom = useRef(false);

  const currentLogProvider = useMemo(
    () => (currentProject?.integrations || []).find(item => item.enabled && ['render', 'manual'].includes(item.provider))?.provider || 'manual',
    [currentProject]
  );

  const clearProjectWorkspace = useCallback(() => {
    setProjectFiles({ files: [], tree: [] });
    setSelectedFile('');
    setFileContent('');
  }, []);

  const clearIncidentWorkspace = useCallback(() => {
    setIncidentsList([]);
    setActiveIncidentId(null);
    setActiveIncident(null);
    setIncidentContext(null);
    setIncidentDiff(null);
    setIncidentSandbox(null);
    setIncidentPR(null);
    setTimelineEvents([]);
    setIsDiagnosing(false);
    setRenderLogs([]);
    setRenderLogsMeta(null);
    setHighlightLine(null);
    setFailureReason('');
  }, []);

  const bootstrapApp = useCallback(async () => {
    try {
      const health = await api.getHealth();
      setBackendHealth(health);
      setIsBackendConnected(health.status === 'ok');

      let user = null;
      try {
        user = await api.getCurrentUser();
      } catch (err) {
        if (err.status === 401 || err.response?.status === 401 || String(err.message).includes('401')) {
          setCurrentUser(null);
          setProjects([]);
          setCurrentProject(null);
          setShowProjectWizard(false);
          setShowProjectSelector(false);
          setShowProfileModal(false);
          setShowProjectSettings(false);
          clearProjectWorkspace();
          clearIncidentWorkspace();
          return;
        }
        throw err;
      }

      setCurrentUser(user);
      const projectList = await api.listProjects();
      setProjects(projectList || []);

      if (!projectList || projectList.length === 0) {
        setCurrentProject(null);
        setShowProjectWizard(true);
        setShowProjectSelector(false);
        clearProjectWorkspace();
        clearIncidentWorkspace();
        return;
      }

      let current = null;
      try {
        current = await api.getCurrentProject();
      } catch {
        current = null;
      }

      if ((projectList || []).length === 1) {
        current = current || projectList[0];
        setCurrentProject(current);
        setShowProjectWizard(false);
        setShowProjectSelector(false);
        selectedProjectOnce.current = true;
      } else {
        setCurrentProject(current || null);
        if (!selectedProjectOnce.current) {
          setShowProjectSelector(true);
        }
      }
    } catch (err) {
      console.error('Failed to bootstrap application:', err);
      setIsBackendConnected(false);
      setBackendHealth(null);
    } finally {
      setIsBootstrapping(false);
    }
  }, [clearIncidentWorkspace, clearProjectWorkspace]);

  const loadProjectFiles = useCallback(async (projectId, keepSelected = true) => {
    if (!projectId) return;
    try {
      const res = await api.getProjectFiles(projectId);
      if (res?.files) {
        setProjectFiles({ files: res.files, tree: res.tree || [] });
        setSelectedFile(prev => {
          if (keepSelected && prev && res.files.includes(prev)) return prev;
          const defaultFile = res.files.find(f => /main|index|readme/i.test(f)) || res.files[0] || '';
          return defaultFile;
        });
      }
    } catch (err) {
      console.warn('Failed to load project files:', err);
      clearProjectWorkspace();
    }
  }, [clearProjectWorkspace]);

  const refreshProjectData = useCallback(async (projectId) => {
    if (!projectId) return;
    try {
      const [project, incidents] = await Promise.all([
        api.getProject(projectId),
        api.listIncidents(projectId),
      ]);
      setCurrentProject(project);
      setIncidentsList(incidents || []);

      setActiveIncidentId(prev => {
        if (prev && (incidents || []).some(item => item.id === prev)) return prev;
        return incidents?.[0]?.id || null;
      });

      if (project?.is_connected) {
        await loadProjectFiles(project.id);
      } else {
        clearProjectWorkspace();
      }
    } catch (err) {
      console.error('Failed to refresh project data:', err);
    }
  }, [clearProjectWorkspace, loadProjectFiles]);

  useEffect(() => {
    bootstrapApp();
    const interval = setInterval(bootstrapApp, 15000);
    return () => clearInterval(interval);
  }, [bootstrapApp]);

  useEffect(() => {
    if (!currentProject?.id || showProjectSelector) return;
    refreshProjectData(currentProject.id);
    const interval = setInterval(() => refreshProjectData(currentProject.id), 8000);
    return () => clearInterval(interval);
  }, [currentProject?.id, refreshProjectData, showProjectSelector]);

  useEffect(() => {
    if (!selectedFile || !currentProject?.id) return;
    let isMounted = true;
    api.getFileContent(selectedFile, currentProject.id)
      .then(res => {
        if (isMounted && res?.content !== undefined) {
          setFileContent(res.content);
        }
      })
      .catch(err => {
        // AI-suggested paths occasionally don't exist in the synced workspace.
        // Show a clear placeholder instead of spamming the console with 404s.
        if (isMounted) {
          setFileContent(
            `# ${selectedFile}\n# This file was not found in the synchronized workspace` +
            (err?.status === 404 ? ' (the agent referenced a path that does not exist).' : '.')
          );
        }
      });
    return () => { isMounted = false; };
  }, [selectedFile, currentProject?.id, fileContentVersion]);

  // Resolve an agent-suggested path against the real workspace file list.
  // Falls back to a unique suffix match (AI paths are sometimes approximate).
  const openProjectFile = useCallback((path) => {
    if (!path) return;
    const files = projectFiles.files || [];
    if (files.includes(path)) {
      setSelectedFile(path);
      return;
    }
    const suffixMatches = files.filter(f => f.endsWith(`/${path}`));
    if (suffixMatches.length === 1) {
      setSelectedFile(suffixMatches[0]);
      return;
    }
    const base = path.split('/').pop();
    const nameMatches = files.filter(f => f === base || f.endsWith(`/${base}`));
    if (nameMatches.length === 1) {
      setSelectedFile(nameMatches[0]);
      return;
    }
    // Let the editor surface a friendly "not found" placeholder.
    setSelectedFile(path);
  }, [projectFiles]);

  const isFetchingIncident = useRef(false);
  const fetchIncidentDetails = useCallback(async (id) => {
    if (!id || isFetchingIncident.current) return;
    isFetchingIncident.current = true;
    try {
      const [inc, ctx, diff, sb, pr] = await Promise.allSettled([
        api.getIncident(id),
        api.getIncidentContext(id),
        api.getIncidentDiff(id),
        api.getIncidentSandbox(id),
        api.getIncidentPR(id)
      ]);

      const incidentData = inc.status === 'fulfilled' ? inc.value : null;
      const contextData = ctx.status === 'fulfilled' ? ctx.value : null;
      const diffData = diff.status === 'fulfilled' ? diff.value : null;
      const sandboxData = sb.status === 'fulfilled' ? sb.value : null;
      const prData = pr.status === 'fulfilled' ? pr.value : null;

      setActiveIncident(incidentData);
      setIncidentContext(contextData);
      setIncidentDiff(diffData);
      setIncidentSandbox(sandboxData);
      setIncidentPR(prData);

      // Drive the diagnosing indicator off the canonical backend status so the
      // UI stays in sync as the incident progresses (including SSE refetches).
      setIsDiagnosing(
        Boolean(incidentData?.status) && ACTIVE_DIAGNOSIS_STATUSES.has(incidentData.status)
      );

      // Highlight the offending line for the selected file in the editor.
      let nextHighlightLine = null;
      const currentSelectedFile = selectedFileRef.current;
      const snippetForFile = currentSelectedFile
        ? contextData?.code_snippets?.[currentSelectedFile]
        : null;
      if (snippetForFile && typeof snippetForFile === 'object' && snippetForFile.error_line != null) {
        nextHighlightLine = snippetForFile.error_line;
      } else {
        const firstSnippet = Object.values(contextData?.code_snippets || {}).find(
          (snippet) => snippet && typeof snippet === 'object' && snippet.error_line != null
        );
        if (firstSnippet) nextHighlightLine = firstSnippet.error_line;
      }
      setHighlightLine(nextHighlightLine);

      // Populate the failure callout with the most informative text available.
      const rootCause = incidentData?.root_cause;
      const reason = rootCause?.reason || rootCause?.root_cause || incidentData?.error_message || '';
      setFailureReason(reason);
    } catch (err) {
      console.error('Failed to fetch incident details:', err);
    } finally {
      isFetchingIncident.current = false;
    }
  }, []);

  useEffect(() => {
    if (activeIncidentId) {
      fetchIncidentDetails(activeIncidentId);
    }
  }, [activeIncidentId, fetchIncidentDetails]);

  useEffect(() => {
    if (!activeIncidentId) return;
    setTimelineEvents([]);
    const unsubscribe = api.subscribeIncidentStream(
      activeIncidentId,
      (eventData) => {
        if (eventData.step || eventData.message) {
          setTimelineEvents(prev => [...prev, eventData]);
        }
        // Workspace content changed — refresh file tree, exit diff mode, and
        // reload the open editor so the applied code shows as normal code.
        if (['changes_applied', 'changes_rolled_back'].includes(eventData.step) && eventData.status !== 'running') {
          if (currentProject?.id) loadProjectFiles(currentProject.id, true);
          setIsDiffMode(false);
          setFileContentVersion(v => v + 1);
        }
        fetchIncidentDetails(activeIncidentId);
      },
      () => console.log('SSE stream closed')
    );
    return () => unsubscribe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIncidentId, fetchIncidentDetails, currentProject?.id]);

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

  const handleAuthenticated = async (user) => {
    setCurrentUser(user);
    setIsBootstrapping(true);
    await bootstrapApp();
  };

  const handleLogout = async () => {
    await api.logout();
    setCurrentUser(null);
    setProjects([]);
    setCurrentProject(null);
    setShowProfileModal(false);
    setShowProjectSettings(false);
    setShowProjectWizard(false);
    setShowProjectSelector(false);
    clearProjectWorkspace();
    clearIncidentWorkspace();
    setIsBootstrapping(false);
  };

  const handleProfileUpdated = (user) => {
    setCurrentUser(user);
  };

  const handleDeleteAccount = async () => {
    await api.deleteCurrentUser();
    setCurrentUser(null);
    setProjects([]);
    setCurrentProject(null);
    setShowProfileModal(false);
    setShowProjectSettings(false);
    setShowProjectWizard(false);
    setShowProjectSelector(false);
    clearProjectWorkspace();
    clearIncidentWorkspace();
    setIsBootstrapping(false);
  };

  const handleRenameProject = async (project, name) => {
    await api.updateProject(project.id, { name });
    const refreshedProjects = await api.listProjects();
    setProjects(refreshedProjects || []);
    if (currentProject?.id === project.id) {
      await refreshProjectData(project.id);
    }
  };

  const handleDuplicateProject = async (project, name) => {
    const duplicated = await api.duplicateProject(project.id, name || `${project.name} Copy`);
    const refreshedProjects = await api.listProjects();
    setProjects(refreshedProjects || []);
    setShowProjectSelector(true);
    return duplicated;
  };

  const handleDeleteProject = async (project) => {
    await api.deleteProject(project.id);
    const refreshedProjects = await api.listProjects();
    setProjects(refreshedProjects || []);
    if (currentProject?.id === project.id) {
      clearIncidentWorkspace();
      clearProjectWorkspace();
      if (refreshedProjects?.length > 0) {
        await handleSelectProject(refreshedProjects[0]);
      } else {
        setCurrentProject(null);
        setShowProjectWizard(true);
      }
    }
  };

  const handleProjectSettingsSaved = async () => {
    if (currentProject?.id) {
      await refreshProjectData(currentProject.id);
      const refreshedProjects = await api.listProjects();
      setProjects(refreshedProjects || []);
    }
  };

  const handleProjectCreated = async (project) => {
    selectedProjectOnce.current = true;
    setShowProjectWizard(false);
    setShowProjectSelector(false);
    setCurrentProject(project);
    await bootstrapApp();
  };

  const handleSelectProject = async (project) => {
    try {
      selectedProjectOnce.current = true;
      const activated = await api.activateProject(project.id);
      setShowProjectSelector(false);
      setShowProjectWizard(false);
      setCurrentProject(activated);
      clearIncidentWorkspace();
      clearProjectWorkspace();
      await refreshProjectData(activated.id);
    } catch (err) {
      alert(`Unable to open project: ${err.message}`);
    }
  };

  const showRenderLogs = useCallback((payload) => {
    const logs = Array.isArray(payload?.logs) ? payload.logs : [];
    setRenderLogs(logs);
    setRenderLogsMeta({
      projectId: payload?.project_id || currentProject?.id || '',
      serviceId: payload?.service_id || '',
      serviceName: payload?.service_name || '',
      retrieved: payload?.logs_retrieved ?? logs.length,
      message: payload?.message || '',
    });
    setActiveBottomTab('logs');
    setIsBottomCollapsed(false);
  }, [currentProject?.id]);

  const handleViewRenderLogs = async () => {
    if (!currentProject?.id) {
      setShowProjectSelector(true);
      return;
    }
    try {
      const payload = await api.getRenderLogs(currentProject.id);
      showRenderLogs(payload);
    } catch (err) {
      alert(`Failed to retrieve Render logs: ${err.message}`);
    }
  };

  const handleSyncRender = async () => {
    if (!currentProject?.id) {
      setShowProjectSelector(true);
      return;
    }
    try {
      const res = await api.syncRenderLogs(null, currentProject.id);
      if (res.status === 'error' || res.status === 'unconfigured') {
        alert(res.message || 'Failed to retrieve logs.');
        return;
      }
      // Sync returns the sanitized source entries as well as detector results, so
      // users can inspect an all-healthy log window instead of seeing only "0 incidents".
      showRenderLogs(res);
      if (res.incidents_created?.length > 0) {
        setActiveIncidentId(res.incidents_created[0]);
        if (res.diagnosis_started) setIsDiagnosing(true);
        await refreshProjectData(currentProject.id);
        fetchIncidentDetails(res.incidents_created[0]);
      } else if (!res.incidents_created?.length) {
        // No incidents detected - surface this clearly to the user
        alert(
          `Synced ${res.logs_retrieved ?? 0} log entries but found no ` +
          `new incidents. Check the Logs tab, or use "Ingest & Start ` +
          `Diagnosis" to manually diagnose a specific error.`
        );
        return;
      }
    } catch (err) {
      alert(`Failed to sync logs: ${err.message}`);
    }
  };

  const handleUseRenderLogs = async () => {
    setShowIngestModal(false);
    await handleSyncRender();
  };

  const handleIngestIncident = async (e) => {
    if (e) e.preventDefault();
    if (!currentProject?.id) {
      setShowProjectSelector(true);
      return;
    }
    if (!ingestForm.log_text && !ingestForm.message) {
      alert('Please enter log text or an error message.');
      return;
    }

    setIsIngesting(true);
    try {
      const res = await api.ingestIncident({
        ...ingestForm,
        project_id: currentProject.id,
        raw_logs: ingestForm.log_text,
        stack_trace: ingestForm.log_text,
        auto_diagnose: true,
      });
      if (res?.incident_id) {
        setActiveIncidentId(res.incident_id);
        setActiveBottomTab('logs');
        setIsBottomCollapsed(false);
        setShowIngestModal(false);
        setIsDiagnosing(true);
        setIngestForm({ source: 'manual', message: '', log_text: '', endpoint: '', method: 'GET' });
        await refreshProjectData(currentProject.id);
        fetchIncidentDetails(res.incident_id);
      }
    } catch (err) {
      alert(`Ingestion failed: ${err.message}`);
    } finally {
      setIsIngesting(false);
    }
  };

  const handleStartDiagnosis = async () => {
    if (!currentProject?.id) {
      setShowProjectSelector(true);
      return;
    }

    // Resume only when the current incident is genuinely mid-flight (running
    // or paused waiting for approval). A finished/failed historical incident
    // is never re-diagnosed silently — the button starts a NEW diagnosis for
    // the current production state instead.
    if (activeIncidentId && activeIncident && ACTIVE_DIAGNOSIS_STATUSES.has(activeIncident.status)) {
      try {
        setIsDiagnosing(true);
        await api.diagnoseIncident(activeIncidentId);
        await fetchIncidentDetails(activeIncidentId);
      } catch (err) {
        alert(`Diagnosis failed: ${err.message}`);
        setIsDiagnosing(false);
      }
      return;
    }

    if (currentLogProvider === 'render') {
      await handleSyncRender();
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
      // A paused/stuck incident has no running worker, but the user still
      // expects Stop to clear the diagnosing state. Refresh and only surface
      // unexpected failures.
      setIsDiagnosing(false);
      await fetchIncidentDetails(activeIncidentId);
      const detail = String(err.message || '');
      if (!/no active diagnosis/i.test(detail)) {
        alert(`Failed to stop diagnosis: ${detail}`);
      }
    }
  };

  const handleApproveFix = async (approved) => {
    // Legacy entry point (diff-view buttons). Route to the Keep/Reject flow.
    if (approved) return handleKeepChanges();
    return handleRejectChanges();
  };

  // "Keep Changes": apply the AI patch to the real workspace, then the backend
  // verifies it in an isolated copy of the pre-apply state. If verification
  // fails the workspace is rolled back automatically.
  const handleKeepChanges = async () => {
    if (!activeIncidentId) return;
    try {
      setIsDiagnosing(true);
      if (activeIncident?.status === 'AWAITING_FIX_APPROVAL') {
        await api.approveFixProposal(activeIncidentId, true);
      } else {
        await api.applyFix(activeIncidentId);
      }
      setFileContentVersion(v => v + 1);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Keep Changes failed: ${err.message}`);
    }
  };

  const handleRejectChanges = async () => {
    if (!activeIncidentId) return;
    try {
      if (activeIncident?.status === 'AWAITING_FIX_APPROVAL') {
        await api.approveFixProposal(activeIncidentId, false);
      } else {
        await api.approveFix(activeIncidentId, false);
      }
      setIsDiagnosing(false);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to reject the patch: ${err.message}`);
    }
  };

  const handleApplyFix = async () => {
    if (!activeIncidentId) return;
    try {
      const res = await api.applyFix(activeIncidentId);
      if (res?.applied) {
        if (currentProject?.id) await loadProjectFiles(currentProject.id, true);
        setFileContentVersion(v => v + 1);
        setIsDiffMode(false);
      }
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      alert(`Failed to apply the patch: ${err.message}`);
    }
  };

  const handleCommitChanges = async () => {
    if (!activeIncidentId) return;
    try {
      const res = await api.commitFix(activeIncidentId);
      if (res?.sha) {
        await fetchIncidentDetails(activeIncidentId);
      }
    } catch (err) {
      alert(`Commit failed: ${err.message}`);
    }
  };

  const handleApproveFileRead = async (approved) => {
    if (!activeIncidentId) return;
    try {
      setIsDiagnosing(Boolean(approved));
      await api.approveFileRead(activeIncidentId, approved);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Failed to record file read approval: ${err.message}`);
    }
  };

  const handleApproveFixProposal = async (approved) => {
    if (!activeIncidentId) return;
    try {
      setIsDiagnosing(Boolean(approved));
      await api.approveFixProposal(activeIncidentId, approved);
      await fetchIncidentDetails(activeIncidentId);
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Failed to record fix approval: ${err.message}`);
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

  const isConnected = Boolean(currentProject?.is_connected);
  const showFullScreenWizard = !isBootstrapping && currentUser && projects.length === 0;

  if (!isBootstrapping && !currentUser) {
    return <LoginPage onAuthenticated={handleAuthenticated} />;
  }

  if (showFullScreenWizard) {
    return (
      <ProjectSetupWizard
        isOpen
        fullScreen
        onCreated={handleProjectCreated}
      />
    );
  }

  if (isBootstrapping && !currentProject) {
    return (
      <div style={{ width: '100vw', height: '100vh', backgroundColor: '#0b1020', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-primary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Loader2 size={18} className="spin" />
          <span>Loading API Doctor…</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      <TopBar
        projects={projects}
        currentUser={currentUser}
        activeIncident={activeIncident}
        onStartDiagnosis={handleStartDiagnosis}
        onStopDiagnosis={handleStopDiagnosis}
        onSyncRender={handleSyncRender}
        onViewRenderLogs={handleViewRenderLogs}
        onOpenIngestModal={() => setShowIngestModal(true)}
        onOpenProjectWizard={() => setShowProjectWizard(true)}
        onOpenProjectSelector={() => setShowProjectSelector(true)}
        onOpenProjectSettings={() => setShowProjectSettings(true)}
        onOpenProfile={() => setShowProfileModal(true)}
        onSelectProject={handleSelectProject}
        onLogout={handleLogout}
        isDiagnosing={isDiagnosing}
        isBackendConnected={isBackendConnected}
        backendHealth={backendHealth}
        currentProject={currentProject}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
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
              ...Object.fromEntries((incidentContext?.implicated_files || []).map(path => [path, isDiagnosing ? 'reading' : 'analyzed'])),
              ...Object.fromEntries((incidentDiff?.files_changed || []).map(path => [path, 'modified']))
            }}
            filesList={projectFiles.files}
            filesTree={projectFiles.tree}
            projectName={currentProject?.name || 'Workspace'}
            onRefresh={isConnected ? () => loadProjectFiles(currentProject.id, false) : undefined}
            explorerWidth={explorerWidth}
            isExplorerOpen={isExplorerOpen}
            isConnected={isConnected}
          />

          {isExplorerOpen && (
            <div className="resize-handle-col" onMouseDown={() => { isDraggingExplorer.current = true; document.body.style.cursor = 'col-resize'; }} />
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
            isProjectConnected={isConnected}
          />

          {isDoctorOpen && (
            <div className="resize-handle-col" onMouseDown={() => { isDraggingDoctor.current = true; document.body.style.cursor = 'col-resize'; }} />
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
            onKeepChanges={handleKeepChanges}
            onRejectChanges={handleRejectChanges}
            onApplyFix={handleApplyFix}
            onCommitChanges={handleCommitChanges}
            onApproveFileRead={handleApproveFileRead}
            onCreatePR={handleCreatePR}
            onSelectIncident={(id) => setActiveIncidentId(id)}
            onSyncRender={handleSyncRender}
            onOpenIngestModal={() => setShowIngestModal(true)}
            doctorWidth={doctorWidth}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            setSelectedFile={openProjectFile}
            setIsDiffMode={setIsDiffMode}
          />
        </div>

        {!isBottomCollapsed && (
          <div className="resize-handle-row" onMouseDown={() => { isDraggingBottom.current = true; document.body.style.cursor = 'row-resize'; }} />
        )}

        <BottomPanel
          activeIncident={activeIncident}
          incidentContext={incidentContext}
          incidentDiff={incidentDiff}
          incidentSandbox={incidentSandbox}
          renderLogs={renderLogs}
          renderLogsMeta={renderLogsMeta}
          onRefreshRenderLogs={currentLogProvider === 'render' ? handleViewRenderLogs : undefined}
          activeBottomTab={activeBottomTab}
          setActiveBottomTab={setActiveBottomTab}
          bottomHeight={bottomHeight}
          isBottomCollapsed={isBottomCollapsed}
          setIsBottomCollapsed={setIsBottomCollapsed}
        />
      </div>

      <ProjectSetupWizard
        isOpen={showProjectWizard}
        onClose={() => setShowProjectWizard(false)}
        onCreated={handleProjectCreated}
      />

      <ProjectSelectorModal
        isOpen={showProjectSelector}
        projects={projects}
        currentProjectId={currentProject?.id}
        onSelectProject={handleSelectProject}
        onRenameProject={handleRenameProject}
        onDuplicateProject={handleDuplicateProject}
        onDeleteProject={handleDeleteProject}
        onNewProject={() => { setShowProjectSelector(false); setShowProjectWizard(true); }}
      />

      <ProjectSettingsModal
        isOpen={showProjectSettings}
        currentProject={currentProject}
        onClose={() => setShowProjectSettings(false)}
        onSaved={handleProjectSettingsSaved}
      />

      <ProfileModal
        isOpen={showProfileModal}
        user={currentUser}
        projects={projects}
        currentProject={currentProject}
        incidentsCount={incidentsList.length}
        onClose={() => setShowProfileModal(false)}
        onUpdated={handleProfileUpdated}
        onLogout={handleLogout}
        onDeleteAccount={handleDeleteAccount}
      />

      {showIngestModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(3px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '10px', padding: '24px', width: '560px', boxShadow: '0 16px 40px rgba(0,0,0,0.6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={18} style={{ color: 'var(--color-accent)' }} />
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Ingest Production Failure or Stack Trace</h3>
              </div>
              <button onClick={() => setShowIngestModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px', lineHeight: 1.5 }}>
              Paste runtime logs or an error traceback when you want to diagnose a manual incident.
              {currentLogProvider === 'render' ? ' This project also supports automatic Render log retrieval.' : ''}
            </p>

            {currentLogProvider === 'render' && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '12px', marginBottom: '14px', backgroundColor: 'rgba(124, 140, 248, 0.08)', border: '1px solid rgba(124, 140, 248, 0.25)', borderRadius: '8px' }}>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>Pull logs automatically from Render</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.4 }}>API Doctor will fetch runtime logs from the configured service, create incidents from detected failures, and open them in the Logs tab.</div>
                </div>
                <button type="button" onClick={handleUseRenderLogs} className="btn-outline" style={{ whiteSpace: 'nowrap' }}>
                  <Server size={14} />
                  <span>Use Render Logs</span>
                </button>
              </div>
            )}

            <form onSubmit={handleIngestIncident} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Source:</label>
                  <select value={ingestForm.source} onChange={e => setIngestForm({ ...ingestForm, source: e.target.value })} style={{ width: '100%', padding: '6px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px' }}>
                    <option value="manual">Manual Error Log</option>
                    <option value="github_actions">GitHub Actions / CI</option>
                    <option value="render">Render Runtime</option>
                  </select>
                </div>
                <div style={{ flex: 2 }}>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Endpoint / Route (Optional):</label>
                  <input type="text" placeholder="e.g. POST /api/v1/checkout" value={ingestForm.endpoint} onChange={e => setIngestForm({ ...ingestForm, endpoint: e.target.value })} style={{ width: '100%', padding: '6px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '12px', fontFamily: 'var(--font-mono)' }} />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>Raw Log / Stack Trace:</label>
                <textarea rows={8} value={ingestForm.log_text} onChange={e => setIngestForm({ ...ingestForm, log_text: e.target.value })} required style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-primary)', fontSize: '11px', fontFamily: 'var(--font-mono)', outline: 'none', resize: 'vertical' }} />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '6px' }}>
                <button type="button" onClick={() => setShowIngestModal(false)} className="btn-outline">Cancel</button>
                <button type="submit" disabled={isIngesting} className="btn-primary" style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {isIngesting ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  <span>Ingest & Start Diagnosis</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

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
