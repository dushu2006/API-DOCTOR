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
import { useProgressiveTimeline } from './useProgressiveTimeline';
import { normalizedTarget } from './diagnosisTimeline';
import { FileText, Loader2, Server, Sparkles, X } from 'lucide-react';
import './index.css';
import './reference-ui.css';
import './doctor-panel.css';

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
  // VS Code-style file tabs: every file the user opens pins a tab across the
  // top of the editor. Tabs keep their open order, are re-activated by
  // clicking, and closed with the x control (closing the active tab moves
  // focus to the right neighbour, then the left one).
  const [openFiles, setOpenFiles] = useState([]);
  const [fileContent, setFileContent] = useState('');

  const [activeRunId, setActiveRunId] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [runContext, setRunContext] = useState(null);
  const [runDiff, setRunDiff] = useState(null);
  const [runSandbox, setRunSandbox] = useState(null);
  const [runPR, setRunPR] = useState(null);
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
  // The API Doctor panel is the primary interface. The file explorer starts
  // collapsed and the doctor panel is given generous width so the diagnosis
  // timeline is the clear focus instead of the workspace chrome.
  const [isExplorerOpen, setIsExplorerOpen] = useState(false);
  const [isDoctorOpen, setIsDoctorOpen] = useState(true);
  const [isBottomCollapsed, setIsBottomCollapsed] = useState(true);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const [explorerWidth, setExplorerWidth] = useState(220);
  // Give the diagnostic console roughly half of the initial viewport. The
  // workspace remains available as evidence, but no longer competes with the
  // product's primary workflow.
  const [doctorWidth, setDoctorWidth] = useState(() => {
    if (typeof window === 'undefined') return 640;
    return Math.min(760, Math.max(520, Math.round(window.innerWidth * 0.46)));
  });
  const [bottomHeight, setBottomHeight] = useState(220);

  // Progressive, backend-driven timeline. The revealer paces how quickly the
  // (real) backend events are presented so the viewer can follow each step.
  const revealedStages = useProgressiveTimeline(timelineEvents);

  const [highlightLine, setHighlightLine] = useState(null);
  const [failureReason, setFailureReason] = useState('');
  const [fileContentVersion, setFileContentVersion] = useState(0);
  const [isRunActionPending, setIsRunActionPending] = useState(false);

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

  // Explorer badges per file, driven by the run's real read timeline
  // rather than the coarse "diagnosing" flag:
  //   modified — touched by the current patch proposal
  //   reading  — a workspace read of this file is in flight right now
  //   analyzed — the agent finished reading this file
  // Files identified but not yet read (waiting for read approval) get no
  // badge, and a paused/finished run never shows a stale "reading".
  const fileStatuses = useMemo(() => {
    const modified = new Set(runDiff?.files_changed || []);
    const implicated = runContext?.implicated_files || [];

    // The backend records one `file_read` activity event per file read:
    // "Reading <path>" (running), updated in place to
    // "Read <path> · N lines" (done). The latest event per path is that
    // file's real read state.
    const readState = new Map();
    for (const event of activeRun?.activity || []) {
      if (event.step !== 'file_read' || !event.message) continue;
      const match = event.message.match(/^(?:Reading|Read)\s+(.+?)(?:\s+·\s*\d+\s*lines?)?$/);
      if (match) readState.set(match[1].trim(), event.status);
    }

    const statuses = {};
    const awaitingReadApproval = activeRun?.status === 'AWAITING_FILE_READ_APPROVAL';
    for (const path of implicated) {
      if (modified.has(path)) continue; // badge assigned below
      const state = readState.get(path);
      if (state === 'running') statuses[path] = 'reading';
      else if (state === 'done') statuses[path] = 'analyzed';
      else if (awaitingReadApproval) continue; // identified, not read yet
      else if (isDiagnosing) statuses[path] = 'reading';
      else statuses[path] = 'analyzed';
    }
    for (const path of modified) {
      statuses[path] = 'modified';
    }
    return statuses;
  }, [runContext, runDiff, activeRun, isDiagnosing]);

  // Reset every diagnosis surface back to an empty, fresh console.
  const resetActiveRun = useCallback(() => {
    setActiveRunId(null);
    setActiveRun(null);
    setRunContext(null);
    setRunDiff(null);
    setRunSandbox(null);
    setRunPR(null);
    setTimelineEvents([]);
    setIsDiagnosing(false);
    setHighlightLine(null);
    setFailureReason('');
    setIsDiffMode(false);
  }, []);

  const handleFreshStart = useCallback(async () => {
    try {
      await api.resetCurrentRun();
    } catch (err) {
      if (!err?.isNetworkError) console.warn('Could not clear diagnosis state:', err);
    } finally {
      resetActiveRun();
    }
  }, [resetActiveRun]);

  const clearProjectWorkspace = useCallback(() => {
    setProjectFiles({ files: [], tree: [] });
    setSelectedFile('');
    setOpenFiles([]);
    setFileContent('');
  }, []);

  // Pin a tab for every file that gets opened; reselecting an already-open
  // path just activates its existing tab (no duplicates).
  useEffect(() => {
    if (!selectedFile) return;
    setOpenFiles(prev => (prev.includes(selectedFile) ? prev : [...prev, selectedFile]));
  }, [selectedFile]);

  const handleSelectTab = (path) => {
    openProjectFile(path);
    setIsDiffMode(false);
  };

  const handleCloseTab = (path) => {
    const idx = openFiles.indexOf(path);
    if (idx === -1) return;
    const next = openFiles.filter(p => p !== path);
    setOpenFiles(next);
    if (path !== selectedFile) return; // closing a background tab keeps the editor put
    const neighbour = next[Math.min(idx, next.length - 1)] || '';
    setSelectedFile(neighbour);
    if (!neighbour) setFileContent('');
  };

  const clearRunWorkspace = useCallback(() => {
    setActiveRunId(null);
    setActiveRun(null);
    setRunContext(null);
    setRunDiff(null);
    setRunSandbox(null);
    setRunPR(null);
    setTimelineEvents([]);
    setIsDiagnosing(false);
    setRenderLogs([]);
    setRenderLogsMeta(null);
    setHighlightLine(null);
    setFailureReason('');
    setOpenFiles([]);
    setSelectedFile('');
    setFileContent('');
  }, []);

  const bootstrapApp = useCallback(async () => {
    let health = null;
    try {
      try {
        health = await api.getHealth();
        setBackendHealth(health);
        setIsBackendConnected(health.status === 'ok');
      } catch (err) {
        // /health is informational. A 500 here used to abort bootstrap entirely,
        // which hid the login/workspace behind a spinner after a project-store
        // inconsistency. Only a true network outage should stop the rest of boot.
        if (err?.isNetworkError) {
          setIsBackendConnected(false);
          setBackendHealth(null);
          return;
        }
        console.warn('Health check failed:', err);
        setBackendHealth(null);
        setIsBackendConnected(true);
      }

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
          clearRunWorkspace();
          return;
        }
        throw err;
      }

      setCurrentUser(user);
      const projectList = await api.listProjects();
      setProjects(projectList || []);

      if (!projectList || projectList.length === 0) {
        setCurrentProject(null);
        // A fresh account with no project always lands on the onboarding
        // wizard — a real repository must be connected before diagnosis.
        setShowProjectWizard(true);
        setShowProjectSelector(false);
        clearProjectWorkspace();
        clearRunWorkspace();
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
      // A restarting backend is an expected, self-healing condition: mark the
      // UI disconnected and let the next poll reconnect, without logging an
      // error for every retry.
      if (!err?.isNetworkError) {
        console.error('Failed to bootstrap application:', err);
      }
      setIsBackendConnected(false);
      setBackendHealth(null);
    } finally {
      setIsBootstrapping(false);
    }
  }, [clearRunWorkspace, clearProjectWorkspace]);

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
      const [project, currentRun] = await Promise.all([
        api.getProject(projectId),
        api.getCurrentRun(projectId),
      ]);
      setCurrentProject(project);
      setActiveRunId(currentRun?.id || null);

      if (project?.is_connected) {
        await loadProjectFiles(project.id);
      } else {
        clearProjectWorkspace();
      }
    } catch (err) {
      // Keep the last known project state on a transient outage so the
      // workspace does not blank out while the backend restarts.
      if (!err?.isNetworkError) {
        console.error('Failed to refresh project data:', err);
      }
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

  // While API Doctor is reading source, keep the editor focused on the exact
  // file it is examining so the viewer sees the live inspection in context.
  useEffect(() => {
    const readStage = revealedStages.find((stage) => stage.id === 'read');
    if (!readStage?.rows?.length) return;
    const last = readStage.rows[readStage.rows.length - 1];
    if (last.step !== 'file_read' || last.status === 'failed') return;
    const target = normalizedTarget(last.message);
    if (target && target !== selectedFileRef.current) {
      openProjectFile(target);
    }
  }, [revealedStages, openProjectFile]);

  // SSE updates and button handlers can request the same run at nearly the
  // same time. Keep the newest response, rather than dropping a required
  // post-action refresh while an older request is in flight.
  const runFetchVersion = useRef(0);
  const fetchRunDetails = useCallback(async (id) => {
    if (!id) return;
    const requestVersion = ++runFetchVersion.current;
    try {
      const [run, ctx, diff, sb, pr] = await Promise.allSettled([
        api.getRun(id),
        api.getRunContext(id),
        api.getRunDiff(id),
        api.getRunSandbox(id),
        api.getRunPR(id)
      ]);

      // If the core run endpoint 404s, the backend no longer has this run
      // (process restart, replaced by a fresh diagnosis, or explicit reset).
      // Clear the stale activeRunId so the UI falls back to the idle console
      // instead of hammering 404s forever.
      const runRejected = run.status === 'rejected';
      const runNotFound = runRejected && (run.reason?.status === 404 || String(run.reason?.message || '').toLowerCase().includes('not found'));
      if (runNotFound) {
        if (requestVersion !== runFetchVersion.current) return;
        // Avoid resetting if we already moved to a newer run.
        if (id === activeRunId || activeRunId === null) {
          resetActiveRun();
        }
        return;
      }

      const runData = run.status === 'fulfilled' ? run.value : null;
      const contextData = ctx.status === 'fulfilled' ? ctx.value : null;
      const diffData = diff.status === 'fulfilled' ? diff.value : null;
      const sandboxData = sb.status === 'fulfilled' ? sb.value : null;
      const prData = pr.status === 'fulfilled' ? pr.value : null;

      // An older response must not restore a pause-state after an approval has
      // already moved the run forward.
      if (requestVersion !== runFetchVersion.current) return;

      setActiveRun(runData);
      setRunContext(contextData);
      setRunDiff(diffData);
      setRunSandbox(sandboxData);
      setRunPR(prData);

      // Drive the diagnosing indicator off the canonical backend status so the
      // UI stays in sync as the run progresses (including SSE refetches).
      setIsDiagnosing(
        Boolean(runData?.status) && ACTIVE_DIAGNOSIS_STATUSES.has(runData.status)
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
      const rootCause = runData?.root_cause;
      const reason = rootCause?.reason || rootCause?.root_cause || runData?.error_message || '';
      setFailureReason(reason);
    } catch (err) {
      console.error('Failed to fetch run details:', err);
    }
  }, [activeRunId, resetActiveRun]);

  useEffect(() => {
    if (activeRunId) {
      fetchRunDetails(activeRunId);
    } else {
      // Fresh state — drop any stale run data so the panel, editor and
      // bottom panel render the idle console instead of a previous report.
      resetActiveRun();
    }
  }, [activeRunId, fetchRunDetails, resetActiveRun]);

  useEffect(() => {
    if (!activeRunId) return;
    setTimelineEvents([]);
    const unsubscribe = api.subscribeRunStream(
      activeRunId,
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
        fetchRunDetails(activeRunId);
      },
      () => console.log('SSE stream closed')
    );
    return () => unsubscribe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId, fetchRunDetails, currentProject?.id]);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDraggingExplorer.current) {
        setExplorerWidth(Math.min(Math.max(e.clientX - 48, 160), 450));
      } else if (isDraggingDoctor.current) {
        setDoctorWidth(Math.min(Math.max(window.innerWidth - e.clientX, 420), 840));
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
    clearRunWorkspace();
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
    clearRunWorkspace();
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
      clearRunWorkspace();
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
      clearRunWorkspace();
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
    resetActiveRun();
    setIsDiagnosing(true);
    try {
      const res = await api.syncRenderLogs(null, currentProject.id);
      if (res.status === 'error' || res.status === 'unconfigured') {
        setIsDiagnosing(false);
        alert(res.message || 'Failed to retrieve logs.');
        return;
      }
      // Sync exposes this point-in-time log window and, when an error is found,
      // starts exactly one fresh diagnosis.
      showRenderLogs(res);
      if (res.run_id) {
        // Logs remain available on demand, but the diagnosis keeps the full
        // vertical workspace instead of opening a competing bottom panel.
        setIsBottomCollapsed(true);
        setActiveRunId(res.run_id);
        if (res.diagnosis_started) setIsDiagnosing(true);
        fetchRunDetails(res.run_id);
      } else {
        resetActiveRun();
        alert(
          `Synced ${res.logs_retrieved ?? 0} log entries but found no error. ` +
          `Check the Logs tab, or paste a specific error to start diagnosis.`
        );
      }
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Failed to sync logs: ${err.message}`);
    }
  };

  const handleUseRenderLogs = async () => {
    setShowIngestModal(false);
    await handleSyncRender();
  };

  const handleIngestRun = async (e) => {
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
    resetActiveRun();
    // Transition to the live console immediately. The first visible operation
    // buffers while the backend creates the run, rather than leaving the user
    // staring at an unchanged form until several fast operations have finished.
    setIsDiagnosing(true);
    setShowIngestModal(false);
    try {
      const res = await api.ingestRun({
        ...ingestForm,
        project_id: currentProject.id,
        raw_logs: ingestForm.log_text,
        stack_trace: ingestForm.log_text,
        auto_diagnose: true,
      });
      if (!res?.run_id) throw new Error('Backend did not return a diagnosis run.');
      if (res.run_id) {
        setActiveRunId(res.run_id);
        setShowIngestModal(false);
        setIsDiagnosing(true);
        setIngestForm({ source: 'manual', message: '', log_text: '', endpoint: '', method: 'GET' });
        await refreshProjectData(currentProject.id);
        fetchRunDetails(res.run_id);
      }
    } catch (err) {
      setIsDiagnosing(false);
      setShowIngestModal(true);
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

    // Resume only when the current run is genuinely mid-flight (running
    // or paused waiting for approval). A completed run is never restarted
    // silently — the button starts from the current production state.
    if (activeRunId && activeRun && ACTIVE_DIAGNOSIS_STATUSES.has(activeRun.status)) {
      try {
        setIsDiagnosing(true);
        await api.diagnoseRun(activeRunId);
        await fetchRunDetails(activeRunId);
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
    if (!activeRunId) return;
    try {
      await api.cancelDiagnosis(activeRunId);
      setIsDiagnosing(false);
      await fetchRunDetails(activeRunId);
    } catch (err) {
      // A paused/stuck run has no running worker, but the user still
      // expects Stop to clear the diagnosing state. Refresh and only surface
      // unexpected failures.
      setIsDiagnosing(false);
      await fetchRunDetails(activeRunId);
      const detail = String(err.message || '');
      if (!/no active diagnosis/i.test(detail)) {
        alert(`Failed to stop diagnosis: ${detail}`);
      }
    }
  };

  const handleRestart = async () => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    setIsDiagnosing(true);
    try {
      const res = await api.restartRun(activeRunId);
      if (!res?.run_id) throw new Error('Backend did not return a new run.');
      // The backend has already discarded the old run. Move every visible
      // surface and the SSE subscription to the fresh diagnosis immediately.
      setTimelineEvents([]);
      setRunContext(null);
      setRunDiff(null);
      setRunSandbox(null);
      setRunPR(null);
      setActiveRunId(res.run_id);
      if (currentProject?.id) await refreshProjectData(currentProject.id);
      await fetchRunDetails(res.run_id);
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Failed to re-run diagnosis: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  // "Keep Changes": apply the AI patch to the real workspace, then the backend
  // verifies it in an isolated copy of the pre-apply state. If verification
  // fails the workspace is rolled back automatically.
  const handleKeepChanges = async () => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    try {
      setIsDiagnosing(true);
      if (activeRun?.status === 'AWAITING_FIX_APPROVAL') {
        await api.approveFixProposal(activeRunId, true);
      } else {
        await api.applyFix(activeRunId);
      }
      setFileContentVersion(v => v + 1);
      await fetchRunDetails(activeRunId);
    } catch (err) {
      setIsDiagnosing(false);
      await fetchRunDetails(activeRunId);
      alert(`Keep Changes failed: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  const handleRejectChanges = async () => {
    if (!activeRunId) return;
    try {
      if (activeRun?.status === 'AWAITING_FIX_APPROVAL') {
        await api.approveFixProposal(activeRunId, false);
      } else {
        await api.approveFix(activeRunId, false);
      }
      setIsDiagnosing(false);
      await fetchRunDetails(activeRunId);
    } catch (err) {
      alert(`Failed to reject the patch: ${err.message}`);
    }
  };

  const handleApplyFix = async () => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    try {
      const res = await api.applyFix(activeRunId);
      if (res?.applied) {
        if (currentProject?.id) await loadProjectFiles(currentProject.id, true);
        setFileContentVersion(v => v + 1);
        setIsDiffMode(false);
      }
      await fetchRunDetails(activeRunId);
    } catch (err) {
      // The failed apply event carries the conflict reason. Refresh so the
      // panel replaces the unsafe Apply button with a one-click fresh diagnosis.
      await fetchRunDetails(activeRunId);
      alert(`Failed to apply the patch: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  const handleCommitChanges = async () => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    try {
      const res = await api.commitFix(activeRunId);
      if (res?.sha) {
        await fetchRunDetails(activeRunId);
      }
    } catch (err) {
      await fetchRunDetails(activeRunId);
      alert(`Commit failed: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  const handleApproveFileRead = async (approved) => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    try {
      setIsDiagnosing(Boolean(approved));
      await api.approveFileRead(activeRunId, approved);
      await fetchRunDetails(activeRunId);
    } catch (err) {
      setIsDiagnosing(false);
      alert(`Failed to record file read approval: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  const handleCreatePR = async () => {
    if (!activeRunId || isRunActionPending) return;
    setIsRunActionPending(true);
    try {
      await api.createPR(activeRunId);
      await fetchRunDetails(activeRunId);
    } catch (err) {
      // Refresh so the timeline shows the branch_created failure record and
      // any configuration guidance from the backend.
      await fetchRunDetails(activeRunId);
      alert(`Failed to create GitHub PR: ${err.message}`);
    } finally {
      setIsRunActionPending(false);
    }
  };

  const isConnected = Boolean(currentProject?.is_connected);
  // A fresh account with no project always goes through the setup wizard —
  // a real repository must be connected before diagnosis.
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
    <div className="ide-desktop">
      <div className="ide-window-title">
        <span>API Doctor — {currentProject?.name || 'Workspace'}</span>
        <span>{isDiagnosing ? 'Diagnosing' : activeRun ? 'Diagnosis complete' : 'Ready'}</span>
      </div>
      <div className="ide-shell">
      <TopBar
        projects={projects}
        currentUser={currentUser}
        activeRun={activeRun}
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
            hasActiveRun={Boolean(activeRun)}
            onOpenTerminal={() => {
              setIsBottomCollapsed(false);
              setActiveBottomTab('terminal');
            }}
          />

          <Explorer
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            fileStatuses={fileStatuses}
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
            runContext={runContext}
            runDiff={runDiff}
            isDiagnosing={isDiagnosing}
            isDiffMode={isDiffMode}
            setIsDiffMode={setIsDiffMode}
            highlightLine={highlightLine}
            failureReason={failureReason}
            isProjectConnected={isConnected}
            openFiles={openFiles}
            onSelectTab={handleSelectTab}
            onCloseTab={handleCloseTab}
          />

          {isDoctorOpen && (
            <div className="resize-handle-col" onMouseDown={() => { isDraggingDoctor.current = true; document.body.style.cursor = 'col-resize'; }} />
          )}

          <APIDoctorPanel
            activeRun={activeRun}
            runContext={runContext}
            runDiff={runDiff}
            runSandbox={runSandbox}
            runPR={runPR}
            stages={revealedStages}
            isDiagnosing={isDiagnosing}
            isRunActionPending={isRunActionPending}
            onKeepChanges={handleKeepChanges}
            onRejectChanges={handleRejectChanges}
            onApplyFix={handleApplyFix}
            onRestart={handleRestart}
            onCommitChanges={handleCommitChanges}
            onApproveFileRead={handleApproveFileRead}
            onCreatePR={handleCreatePR}
            onNewDiagnosis={handleFreshStart}
            onStartDiagnosis={handleStartDiagnosis}
            onOpenIngestModal={() => setShowIngestModal(true)}
            doctorWidth={doctorWidth}
            projectProfile={currentProject?.profile}
            isDoctorOpen={isDoctorOpen}
            setIsDoctorOpen={setIsDoctorOpen}
            selectedFile={selectedFile}
            setSelectedFile={openProjectFile}
            setIsDiffMode={setIsDiffMode}
          />
        </div>

        {!isBottomCollapsed && (
          <div className="resize-handle-row" onMouseDown={() => { isDraggingBottom.current = true; document.body.style.cursor = 'row-resize'; }} />
        )}

        <BottomPanel
          activeRun={activeRun}
          runContext={runContext}
          runDiff={runDiff}
          runSandbox={runSandbox}
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
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Start a Fresh Diagnosis</h3>
              </div>
              <button onClick={() => setShowIngestModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px', lineHeight: 1.5 }}>
              Paste runtime logs or an error traceback when you want to diagnose a manual run.
              {currentLogProvider === 'render' ? ' This project also supports automatic Render log retrieval.' : ''}
            </p>

            {currentLogProvider === 'render' && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '12px', marginBottom: '14px', backgroundColor: 'rgba(124, 140, 248, 0.08)', border: '1px solid rgba(124, 140, 248, 0.25)', borderRadius: '8px' }}>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>Pull logs automatically from Render</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.4 }}>API Doctor will fetch the current runtime logs and start one fresh diagnosis from the first detected failure.</div>
                </div>
                <button type="button" onClick={handleUseRenderLogs} className="btn-outline" style={{ whiteSpace: 'nowrap' }}>
                  <Server size={14} />
                  <span>Use Render Logs</span>
                </button>
              </div>
            )}

            <form onSubmit={handleIngestRun} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
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
                  <span>Start Fresh Diagnosis</span>
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
    </div>
  );
}
