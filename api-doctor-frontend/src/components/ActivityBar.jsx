import React from 'react';
import {
  Blocks,
  Bot,
  FolderOpen,
  GitBranch,
  Search,
  ShieldCheck,
  SquareTerminal,
} from 'lucide-react';

export default function ActivityBar({
  isDoctorOpen,
  setIsDoctorOpen,
  isExplorerOpen,
  setIsExplorerOpen,
  hasActiveRun,
}) {
  const items = [
    { id: 'explorer', label: 'Explorer', icon: FolderOpen, active: isExplorerOpen, action: () => setIsExplorerOpen(!isExplorerOpen) },
    { id: 'search', label: 'Search', icon: Search, action: () => setIsExplorerOpen(true) },
    { id: 'source', label: 'Source control', icon: GitBranch, action: () => setIsExplorerOpen(true) },
    { id: 'extensions', label: 'Extensions', icon: Blocks, action: () => setIsExplorerOpen(true) },
    { id: 'doctor', label: 'Doctor panel', icon: ShieldCheck, active: isDoctorOpen, action: () => setIsDoctorOpen(!isDoctorOpen), doctor: true },
    { id: 'terminal', label: 'Terminal', icon: SquareTerminal, action: () => undefined },
  ];

  return (
    <aside className="ide-activitybar">
      <div className="ide-activity-items">
        {items.map(item => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              title={item.label}
              className={`${item.active ? 'is-active' : ''}${item.doctor ? ' is-doctor' : ''}`}
              onClick={item.action}
            >
              <Icon size={17} strokeWidth={1.8} />
              {item.doctor && hasActiveRun && <span className="ide-activity-live" />}
            </button>
          );
        })}
      </div>
      <button type="button" className="ide-agent-badge" title="API Doctor agent"><Bot size={13} /></button>
    </aside>
  );
}
