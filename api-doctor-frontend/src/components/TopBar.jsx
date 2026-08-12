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
  X
} from 'lucide-react';

export default function TopBar({
  projects = [],
  currentUser,
  activeIncident,
  onStartDiagnosis,
  onStopDiagnosis,
  onSyncRender,
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

  const confirmStop = () => {
    setShowStopDialog(false);
    onStopDiagnosis();
  };

  return (
    <header style={{
      height: '44px',
      backgroundColor: 'var(--surface-1)',
      borderBottom: '1px solid var(--border-color)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      position: 'relative',
      zIndex: 50
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)', fontWeight: 700, fontSize: '13px' }}>
          <div style={{ width: '24px', height: '24px', borderRadius: 'var(--radius-sm)', background: 'var(--color-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#0A0E14', boxShadow: '0 0 10px var(--color-accent-glow)' }}>
            <Stethoscope size={14} />
          </div>
          <span style={{ fontFamily: 'var(--font-heading)', letterSpacing: '0.04em', fontWeight: 700 }}>API DOCTOR</span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setIsProjectMenuOpen(prev => !prev)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '4px'
            }}
            className="hover-bg"
          >
            <span>{currentProjectLabel}</span>
            <ChevronDown size={11} style={{ color: 'var(--text-muted)' }} />
          </button>

          {isProjectMenuOpen && (
            <div style={{ position: 'absolute', top: 'calc(100% + 8px)', left: 0, width: '300px', backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '10px', boxShadow: '0 12px 24px rgba(0,0,0,0.45)', overflow: 'hidden' }}>
              <div style={{ padding: '10px 12px', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.06em', fontWeight: 700, borderBottom: '1px solid var(--border-color)' }}>PROJECTS</div>
              <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
                {projects.map(project => (
                  <button
                    key={project.id}
                    onClick={() => {
                      setIsProjectMenuOpen(false);
                      onSelectProject(project);
                    }}
                    style={{ width: '100%', textAlign: 'left', background: 'transparent', border: 'none', padding: '10px 12px', cursor: 'pointer', color: 'var(--text-primary)' }}
                    className="hover-bg"
                  >
                    <div style={{ fontSize: '12px', fontWeight: 600 }}>{project.name}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{project.github_owner}/{project.github_repo}</div>
                  </button>
                ))}
              </div>
              <div style={{ borderTop: '1px solid var(--border-color)', padding: '8px', display: 'grid', gap: '8px' }}>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectSelector(); }} className="btn-outline" style={{ width: '100%', justifyContent: 'center' }}>
                  <Settings size={14} />
                  <span>Manage Projects</span>
                </button>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectSettings(); }} className="btn-outline" style={{ width: '100%', justifyContent: 'center' }}>
                  <Server size={14} />
                  <span>Project Settings</span>
                </button>
                <button type="button" onClick={() => { setIsProjectMenuOpen(false); onOpenProjectWizard(); }} className="btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                  <PlusCircle size={14} />
                  <span>New Project</span>
                </button>
              </div>
            </div>
          )}
        </div>

        <span style={{ color: 'var(--text-muted)' }}>/</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)', fontSize: '12px', padding: '4px 6px' }}>
          <GitBranch size={13} style={{ color: 'var(--color-accent)' }} />
          <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{currentBranch}</span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: isBackendConnected ? 'var(--color-success)' : 'var(--color-failure)' }} />
          <span>{isBackendConnected ? 'Backend Connected' : 'Disconnected'}</span>
          {backendHealth?.project_count !== undefined && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px' }}>PROJECTS: {backendHealth.project_count}</span>
          )}
        </div>

        <button onClick={handleSyncRenderClick} disabled={isSyncingRender || projectProvider !== 'render'} className="btn-outline" title="Retrieve runtime logs from the configured provider" style={{ padding: '4px 10px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Server size={12} style={{ color: 'var(--color-accent)' }} />
          <span>{isSyncingRender ? 'Syncing...' : 'Sync Render Logs'}</span>
        </button>

        <button onClick={onOpenIngestModal} className="btn-outline" title="Paste production logs or stack trace" style={{ padding: '4px 10px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <PlusCircle size={12} style={{ color: 'var(--color-accent)' }} />
          <span>Manual Error</span>
        </button>

        {isDiagnosing && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'rgba(124, 140, 248, 0.12)', border: '1px solid rgba(124, 140, 248, 0.3)', padding: '3px 10px', borderRadius: '12px', fontSize: '12px', color: 'var(--color-accent)' }}>
            <span className="agent-dot" />
            <span style={{ fontWeight: 500 }}>Diagnosing...</span>
          </div>
        )}

        <div>
          {isDiagnosing ? (
            <button onClick={() => setShowStopDialog(true)} className="btn-danger-outline" style={{ minWidth: '90px', justifyContent: 'center' }}>
              <OctagonAlert size={13} />
              <span>Stop</span>
            </button>
          ) : (
            <button onClick={() => onStartDiagnosis()} className="btn-primary" style={{ minWidth: '120px', justifyContent: 'center' }}>
              <Stethoscope size={13} />
              <span>Start Diagnosis</span>
            </button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div title="Active Incident / Branch" style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)', fontSize: '12px' }}>
          <GitCommit size={15} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--color-warning)' }}>
            {activeIncident ? `#${activeIncident.id.slice(0, 7)}` : currentBranch}
          </span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        <button onClick={onOpenProjectSettings} title="Project settings" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <Settings size={15} />
        </button>

        <button onClick={onOpenProfile} title={userLabel} style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-primary)', fontSize: '10px', fontWeight: 700 }}>
          {currentUser ? userInitials : <User size={14} />}
        </button>
      </div>

      {showStopDialog && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '20px', width: '360px', boxShadow: '0 12px 24px rgba(0,0,0,0.5)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontWeight: 600, color: 'var(--color-failure)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <OctagonAlert size={16} /> Stop Investigation?
              </span>
              <button onClick={() => setShowStopDialog(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Are you sure you want to cancel this diagnosis? The current progress will be recorded.
            </p>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
              <button onClick={onLogout} className="btn-outline">
                <LogOut size={13} />
                <span>Logout</span>
              </button>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setShowStopDialog(false)} className="btn-outline">Cancel</button>
                <button onClick={confirmStop} className="btn-danger-outline">Stop Diagnosis</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
