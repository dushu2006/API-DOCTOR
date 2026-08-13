import React, { useState } from 'react';
import {
  Check,
  ChevronDown,
  GitBranch,
  Network,
  RadioTower,
  Settings,
  Square,
} from 'lucide-react';
import './doctor.css';

const MENUS = ['FILE', 'EDIT', 'SELECTION', 'VIEW', 'GO', 'RUN', 'TERMINAL', 'HELP'];

/** Compact IDE command bar modelled after the supplied desktop reference. */
export default function TopBar({
  projects = [],
  activeRun,
  onStartDiagnosis,
  onStopDiagnosis,
  onOpenProjectWizard,
  onOpenProjectSelector,
  onOpenProjectSettings,
  onOpenProfile,
  onSelectProject,
  isDiagnosing,
  isBackendConnected,
  currentProject,
}) {
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const branch = currentProject?.default_branch || currentProject?.github_branch || 'main';

  const handleMenu = (menu) => {
    if (menu === 'RUN') onStartDiagnosis?.();
    if (menu === 'FILE') onOpenProjectSelector?.();
    if (menu === 'VIEW') onOpenProfile?.();
  };

  return (
    <header className="ide-topbar">
      <div className="ide-topbar-left">
        <button type="button" className="ide-brand" onClick={onOpenProjectSelector}>
          API DOCTOR
        </button>
        <nav className="ide-menu" aria-label="Application menu">
          {MENUS.map(menu => (
            <button type="button" key={menu} onClick={() => handleMenu(menu)}>{menu}</button>
          ))}
        </nav>
      </div>

      <button type="button" className="ide-command" onClick={onOpenProjectSelector} title="Select project">
        <span className="ide-command-search">⌕</span>
        <span>api-doctor&nbsp; / &nbsp;{branch}</span>
      </button>

      <div className="ide-topbar-actions">
        {activeRun && isDiagnosing && (
          <div className="ide-diagnosing-chip">
            <span className="ide-live-dot" />
            DIAGNOSING…
          </div>
        )}
        {activeRun && !isDiagnosing && (
          <div className="ide-complete-chip"><Check size={10} /> COMPLETE</div>
        )}
        {isDiagnosing && (
          <button type="button" className="ide-stop" onClick={onStopDiagnosis}>
            <Square size={9} fill="currentColor" /> STOP
          </button>
        )}

        <div className="ide-project-switcher">
          <button
            type="button"
            className={`ide-connected ${isBackendConnected ? '' : 'is-offline'}`}
            onClick={() => setProjectMenuOpen(value => !value)}
          >
            <span className="ide-connection-dot" />
            {isBackendConnected ? 'CONNECTED' : 'OFFLINE'}
            <ChevronDown size={9} />
          </button>
          {projectMenuOpen && (
            <div className="ide-project-menu">
              <div className="ide-project-menu-title">WORKSPACES</div>
              {projects.map(project => (
                <button
                  type="button"
                  key={project.id}
                  className={project.id === currentProject?.id ? 'is-active' : ''}
                  onClick={() => {
                    setProjectMenuOpen(false);
                    onSelectProject?.(project);
                  }}
                >
                  <span>{project.name}</span>
                  <small>{project.default_branch || 'main'}</small>
                </button>
              ))}
              <div className="ide-project-menu-actions">
                <button type="button" onClick={() => { setProjectMenuOpen(false); onOpenProjectSelector?.(); }}>MANAGE</button>
                <button type="button" onClick={() => { setProjectMenuOpen(false); onOpenProjectWizard?.(); }}>+ NEW</button>
              </div>
            </div>
          )}
        </div>

        <button type="button" className="ide-top-icon" title="Repository"><Network size={15} /></button>
        <button type="button" className="ide-top-icon" title="Runtime connection"><RadioTower size={15} /></button>
        <button type="button" className="ide-top-icon" title="Project settings" onClick={onOpenProjectSettings}><Settings size={16} /></button>
        <span className="ide-branch-mark" title={branch}><GitBranch size={11} /></span>
      </div>
    </header>
  );
}
