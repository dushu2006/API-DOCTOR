import React from 'react';
import { Check, Settings, Square } from 'lucide-react';

/**
 * Compact command bar. Every control performs a real action:
 *   brand        → open project selector
 *   command pill → open project selector (switch workspace)
 *   STOP         → cancel the running diagnosis
 *   settings     → open project settings
 *   account      → open profile / logout
 * Connection state is shown as a quiet OFFLINE chip only when the backend is
 * actually unreachable.
 */
export default function TopBar({
  currentUser,
  activeRun,
  onStopDiagnosis,
  onOpenProjectSelector,
  onOpenProjectSettings,
  onOpenProfile,
  isDiagnosing,
  isBackendConnected,
  currentProject,
}) {
  const branch = currentProject?.default_branch || currentProject?.github_branch || 'main';
  const identifier = currentUser?.email || currentUser?.username || 'U';
  const initial = identifier.charAt(0).toUpperCase();

  return (
    <header className="ide-topbar">
      <div className="ide-topbar-left">
        <button type="button" className="ide-brand" onClick={onOpenProjectSelector}>
          API DOCTOR
        </button>
      </div>

      <button
        type="button"
        className="ide-command"
        onClick={onOpenProjectSelector}
        title="Switch project"
      >
        <span className="ide-command-search">⌕</span>
        <span>
          {currentProject?.name || 'api-doctor'}&nbsp; / &nbsp;{branch}
        </span>
      </button>

      <div className="ide-topbar-actions">
        {!isBackendConnected && (
          <span className="ide-offline-chip" title="Backend is unreachable">
            <span className="ide-connection-dot is-offline" /> OFFLINE
          </span>
        )}
        {activeRun && isDiagnosing && (
          <span className="ide-diagnosing-chip">
            <span className="ide-live-dot" /> DIAGNOSING…
          </span>
        )}
        {activeRun && !isDiagnosing && (
          <span className="ide-complete-chip">
            <Check size={10} /> COMPLETE
          </span>
        )}
        {isDiagnosing && (
          <button type="button" className="ide-stop" onClick={onStopDiagnosis}>
            <Square size={9} fill="currentColor" /> STOP
          </button>
        )}

        <button
          type="button"
          className="ide-top-icon"
          title="Project settings"
          onClick={onOpenProjectSettings}
        >
          <Settings size={16} />
        </button>

        <button type="button" className="ide-account" title="Account" onClick={onOpenProfile}>
          <span className="ide-account-avatar">{initial}</span>
        </button>
      </div>
    </header>
  );
}
