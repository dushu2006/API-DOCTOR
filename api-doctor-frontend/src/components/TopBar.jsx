import React, { useState } from 'react';
import { 
  Stethoscope, 
  GitBranch, 
  CheckCircle2, 
  OctagonAlert, 
  Settings, 
  User, 
  GitCommit, 
  ChevronDown,
  X,
  Radio,
  RefreshCw,
  PlusCircle,
  Server
} from 'lucide-react';

export default function TopBar({ 
  activeIncident, 
  onStartDiagnosis, 
  onStopDiagnosis, 
  onSyncRender,
  onOpenIngestModal,
  onOpenConnectModal,
  isDiagnosing,
  isBackendConnected,
  backendHealth,
  currentProject
}) {
  const [showBranches, setShowBranches] = useState(false);
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [isSyncingRender, setIsSyncingRender] = useState(false);

  const projectName = currentProject?.name || (currentProject?.github_owner && currentProject?.github_repo ? `${currentProject.github_owner}/${currentProject.github_repo}` : 'API-DOCTOR');
  const currentBranch = currentProject?.github_branch || 'main';

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
      {/* Left section: Logo & Project/Branch Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)', fontWeight: 600, fontSize: '13px' }}>
          <div style={{
            width: '24px',
            height: '24px',
            borderRadius: '4px',
            background: 'var(--color-accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff'
          }}>
            <Stethoscope size={14} />
          </div>
          <span style={{ fontFamily: 'var(--font-heading)', letterSpacing: '0.02em' }}>API DOCTOR</span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        {/* Project & Branch Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button 
            onClick={onOpenConnectModal}
            title="Click to configure or switch repository"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '4px'
            }}
            className="hover-bg"
          >
            <span>{projectName}</span>
            <ChevronDown size={11} style={{ color: 'var(--text-muted)' }} />
          </button>

          <span style={{ color: 'var(--text-muted)' }}>/</span>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)', fontSize: '12px', padding: '4px 6px' }}>
            <GitBranch size={13} style={{ color: 'var(--color-accent)' }} />
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{currentBranch}</span>
          </div>
        </div>
      </div>

      {/* Middle Section: Actions & Connection Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Backend Connection status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span style={{ 
            width: '6px', 
            height: '6px', 
            borderRadius: '50%', 
            backgroundColor: isBackendConnected ? 'var(--color-success)' : 'var(--color-failure)' 
          }} />
          <span>{isBackendConnected ? 'Backend Connected' : 'Disconnected'}</span>
          {isBackendConnected && backendHealth?.ai_provider && (
            <span style={{
              color: backendHealth.ai_provider === 'mock' ? 'var(--color-warning)' : 'var(--color-success)',
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              marginLeft: '4px'
            }}>
              AI: {backendHealth.ai_provider.toUpperCase()}
            </span>
          )}
        </div>

        {/* Sync Render Logs Button */}
        <button 
          onClick={handleSyncRenderClick}
          disabled={isSyncingRender}
          className="btn-outline"
          title="Retrieve runtime logs from Render service"
          style={{ padding: '4px 10px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <Server size={12} style={{ color: 'var(--color-accent)' }} />
          <span>{isSyncingRender ? 'Syncing Render...' : 'Sync Render Logs'}</span>
        </button>

        {/* Ingest Log / Error Button */}
        <button 
          onClick={onOpenIngestModal}
          className="btn-outline"
          title="Paste production logs or stack trace"
          style={{ padding: '4px 10px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <PlusCircle size={12} style={{ color: 'var(--color-accent)' }} />
          <span>Ingest Log</span>
        </button>

        {/* Diagnosis Status Pill */}
        {isDiagnosing && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: 'rgba(124, 140, 248, 0.12)',
            border: '1px solid rgba(124, 140, 248, 0.3)',
            padding: '3px 10px',
            borderRadius: '12px',
            fontSize: '12px',
            color: 'var(--color-accent)'
          }}>
            <span className="agent-dot" />
            <span style={{ fontWeight: 500 }}>Diagnosing...</span>
          </div>
        )}

        {/* Main Diagnose / Stop CTA */}
        <div>
          {isDiagnosing ? (
            <button 
              onClick={() => setShowStopDialog(true)}
              className="btn-danger-outline"
              style={{ minWidth: '90px', justifyContent: 'center' }}
            >
              <OctagonAlert size={13} />
              <span>Stop</span>
            </button>
          ) : (
            <button 
              onClick={() => onStartDiagnosis()}
              className="btn-primary"
              style={{ minWidth: '90px', justifyContent: 'center' }}
            >
              <Stethoscope size={13} />
              <span>Diagnose</span>
            </button>
          )}
        </div>
      </div>

      {/* Right Section: Git status, Settings, Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div 
          title="Active Incident / Branch"
          style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '4px', 
            color: 'var(--text-muted)', 
            fontSize: '12px' 
          }}
        >
          <GitCommit size={15} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--color-warning)' }}>
            {activeIncident ? `#${activeIncident.id.slice(0, 7)}` : currentBranch}
          </span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        <button 
          onClick={onOpenConnectModal}
          title="Repository & Workspace Settings" 
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
        >
          <Settings size={15} />
        </button>

        <div 
          title="API Doctor Workspace"
          style={{
            width: '26px',
            height: '26px',
            borderRadius: '50%',
            backgroundColor: 'var(--surface-2)',
            border: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            color: 'var(--text-muted)'
          }}
        >
          <User size={14} />
        </div>
      </div>

      {/* Confirm Stop Dialog */}
      {showStopDialog && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.6)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <div style={{
            backgroundColor: 'var(--surface-1)',
            border: '1px solid var(--border-color)',
            borderRadius: '8px',
            padding: '20px',
            width: '360px',
            boxShadow: '0 12px 24px rgba(0,0,0,0.5)'
          }}>
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
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => setShowStopDialog(false)} className="btn-outline">Cancel</button>
              <button onClick={confirmStop} className="btn-danger-outline">Stop Diagnosis</button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
