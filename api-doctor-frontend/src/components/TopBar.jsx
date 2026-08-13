import React, { useMemo, useState } from 'react';
import {
  ChevronDown,
  GitBranch,
  GitCommit,
  LogOut,
  OctagonAlert,
  PlusCircle,
  Server,
  Settings,
  Stethoscope,
  User,
  X,
  RadioTower,
  CheckCircle2,
  XCircle,
  Check
} from 'lucide-react';
import './doctor.css';

/**
 * Top command strip — retro operator band (light grey, beveled controls),
 * matching the reference console: dark status pill on the left, signal /
 * health / settings glyphs, and the raised START DIAGNOSIS push button.
 * Behaviour and props are unchanged.
 */
export default function TopBar({
  projects = [],
  currentUser,
  activeIncident,
  onStartDiagnosis,
  onStopDiagnosis,
  onSyncRender,
  onViewRenderLogs,
  onOpenIngestModal,
  onOpenProjectWizard,
  onOpenProjectSelector,
  onOpenProjectSettings,
  onOpenProfile,
  onSelectProject,
  onLogout,
  isDiagnosing,
  isBackendConnected,
  backendHealth,
  currentProject
}) {
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [isSyncingRender, setIsSyncingRender] = useState(false);
  const [isLoadingRenderLogs, setIsLoadingRenderLogs] = useState(false);
  const [isProjectMenuOpen, setIsProjectMenuOpen] = useState(false);

  const currentBranch = currentProject?.default_branch || currentProject?.github_branch || '—';
  const currentProjectLabel = currentProject?.name || 'Select Project';
  const projectProvider = useMemo(
    () => (currentProject?.integrations || []).find(item => item.enabled && ['render', 'manual'].includes(item.provider))?.provider || 'manual',
    [currentProject]
  );
  const userLabel = currentUser?.full_name || currentUser?.username || 'Profile';
  const userInitials = (userLabel || 'P')
    .split(' ')
    .map(part => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  const handleSyncRenderClick = async () => {
    if (!onSyncRender) return;
    setIsSyncingRender(true);
    try {
      await onSyncRender();
    } finally {
      setIsSyncingRender(false);
    }
  };

  const handleViewRenderLogsClick = async () => {
    if (!onViewRenderLogs) return;
    setIsLoadingRenderLogs(true);
    try {
      await onViewRenderLogs();
    } finally {
      setIsLoadingRenderLogs(false);
    }
  };

  const confirmStop = () => {
    setShowStopDialog(false);
    onStopDiagnosis();
  };

  const incidentDone = Boolean(activeIncident) && !isDiagnosing;

  return (
    <header
      className="dr-band"
      style={{
        height: '46px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        position: 'relative',
        zIndex: 50
      }}
    >
      {/* ---- left: product + project + branch ---- */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 2,
              background: '#17181d',
              border: '1px solid #000',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.15), 0 1px 0 rgba(255,255,255,0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--dr-amber, #f5a524)',
              flexShrink: 0
            }}
          >
            <Stethoscope size={13} />
          </div>
          <span style={{ fontFamily: 'var(--font-heading)', letterSpacing: '0.06em', fontWeight: 700, fontSize: 13, color: 'var(--dr-ink, #15171b)' }}>
            API DOCTOR
          </span>
        </div>

        <div className="dr-band-divider" />

        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setIsProjectMenuOpen(prev => !prev)}
            className="dr-btn"
            style={{ padding: '4px 10px', maxWidth: 220 }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{currentProjectLabel}</span>
            <ChevronDown size={11} />
          </button>

          {isProjectMenuOpen && (
            <div
              className="dr-card"
              style={{
                position: 'absolute',
                top: 'calc(100% + 6px)',
                left: 0,
                width: 300,
                overflow: 'hidden',
                color: 'var(--dr-text, #e8e9ec)',
                zIndex: 100
              }}
            >
              <div className="dr-kicker" style={{ padding: '9px 12px', borderBottom: '1px solid var(--dr-frame-soft, #262930)' }}>PROJECTS</div>
              <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                {projects.map(project => (
                  <button
                    key={project.id}
                    onClick={() => {
                      setIsProjectMenuOpen(false);
                      onSelectProject(project);
                    }}
                    className="dr-file-row"
                    style={{ width: '100%', background: 'transparent', border: 'none', borderBottom: '1px solid var(--dr-frame-soft, #262930)', textAlign: 'left' }}
                  >
                    <span>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--dr-text, #e8e9ec)' }}>{project.name}</div>
                      <div style={{ fontSize: 10, color: 'var(--dr-faint, #6b7078)', fontFamily: 'var(--font-mono)' }}>{project.github_owner}/{project.github_repo}</div>
                    </span>
                  </button>
                ))}
              </div>
              <div style={{ borderTop: '1px solid var(--dr-frame-soft, #262930)', padding: 8, display: 'grid', gap: 6 }}>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectSelector(); }} className="dr-btn" style={{ width: '100%' }}>
                  <Settings size={13} />
                  <span>Manage Projects</span>
                </button>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectSettings(); }} className="dr-btn" style={{ width: '100%' }}>
                  <Server size={13} />
                  <span>Project Settings</span>
                </button>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectWizard(); }} className="dr-btn dr-btn-blue" style={{ width: '100%' }}>
                  <PlusCircle size={13} />
                  <span>New Project</span>
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="dr-well-band">
          <GitBranch size={11} />
          <span>{currentBranch}</span>
        </div>
      </div>

      {/* ---- right: agent status + controls ---- */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        {activeIncident && (
          <span className="dr-pill-dark" title={isDiagnosing ? 'Diagnosis in progress' : 'Diagnosis complete'}>
            {isDiagnosing ? (
              <>
                <span className="dr-pulse" style={{ width: 6, height: 6 }} />
                <span>DIAGNOSING…</span>
              </>
            ) : incidentDone ? (
              <>
                <Check size={10} style={{ color: 'var(--dr-green, #34d17b)' }} />
                <span>Diagnosis complete</span>
              </>
            ) : null}
          </span>
        )}

        <span className="dr-pill-dark" title={isBackendConnected ? 'Backend connected' : 'Backend disconnected'}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: isBackendConnected ? 'var(--dr-green, #34d17b)' : 'var(--dr-red, #f4526a)'
            }}
          />
          <span>{isBackendConnected ? 'Backend Connected' : 'Disconnected'}</span>
          {backendHealth?.project_count !== undefined && (
            <span style={{ color: '#8a8f99' }}>· {backendHealth.project_count} PROJECTS</span>
          )}
        </span>

        <RadioTower size={15} style={{ color: 'rgba(0,0,0,0.62)' }} />
        {isBackendConnected
          ? <CheckCircle2 size={15} style={{ color: 'rgba(0,0,0,0.62)' }} />
          : <XCircle size={15} style={{ color: '#8f1524' }} />}
        <button
          onClick={onOpenProjectSettings}
          title="Project settings"
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', color: 'rgba(0,0,0,0.62)', padding: 2 }}
        >
          <Settings size={15} />
        </button>

        <div className="dr-band-divider" />

        <button onClick={handleViewRenderLogsClick} disabled={isLoadingRenderLogs || projectProvider !== 'render'} className="dr-btn" title="View the latest runtime logs without creating incidents">
          <Server size={12} />
          <span>{isLoadingRenderLogs ? 'Loading…' : 'View Render Logs'}</span>
        </button>

        <button onClick={handleSyncRenderClick} disabled={isSyncingRender || projectProvider !== 'render'} className="dr-btn" title="Retrieve Render logs and detect incidents">
          <Server size={12} />
          <span>{isSyncingRender ? 'Syncing…' : 'Sync & Detect'}</span>
        </button>

        <button onClick={onOpenIngestModal} className="dr-btn" title="Paste production logs or stack trace">
          <PlusCircle size={12} />
          <span>Manual Error</span>
        </button>

        {isDiagnosing ? (
          <button onClick={() => setShowStopDialog(true)} className="dr-btn dr-btn-red dr-btn-band-primary" style={{ minWidth: 90 }}>
            <OctagonAlert size={13} />
            <span>Stop</span>
          </button>
        ) : (
          <button onClick={() => onStartDiagnosis()} className="dr-btn dr-btn-band-primary" style={{ minWidth: 150 }}>
            <Stethoscope size={13} />
            <span>Start Diagnosis</span>
          </button>
        )}

        <div className="dr-band-divider" />

        <div className="dr-well-band" title="Active incident / branch">
          <GitCommit size={12} />
          <span>{activeIncident ? `#${activeIncident.id.slice(0, 7)}` : currentBranch}</span>
        </div>

        <button
          onClick={onOpenProfile}
          title={userLabel}
          className="dr-btn"
          style={{ width: 28, height: 28, padding: 0, fontFamily: 'var(--font-mono)' }}
        >
          {currentUser ? userInitials : <User size={13} />}
        </button>
      </div>

      {showStopDialog && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.65)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="dr-root dr-card" style={{ padding: 20, width: 380, boxShadow: '0 12px 32px rgba(0,0,0,0.6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontWeight: 700, color: 'var(--dr-red)', display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-heading)', letterSpacing: '0.04em' }}>
                <OctagonAlert size={16} /> STOP INVESTIGATION?
              </span>
              <button onClick={() => setShowStopDialog(false)} style={{ background: 'none', border: 'none', color: 'var(--dr-faint)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>
            <p style={{ fontSize: 12, color: 'var(--dr-dim)', marginBottom: 16, lineHeight: 1.5 }}>
              Are you sure you want to cancel this diagnosis? The current progress will be recorded.
            </p>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <button onClick={onLogout} className="dr-btn">
                <LogOut size={13} />
                <span>Logout</span>
              </button>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setShowStopDialog(false)} className="dr-btn">Cancel</button>
                <button onClick={confirmStop} className="dr-btn dr-btn-red">Stop Diagnosis</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
