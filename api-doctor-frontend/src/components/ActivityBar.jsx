import React from 'react';
import { FolderOpen, ShieldCheck, SquareTerminal } from 'lucide-react';

/**
 * Left activity rail. Only real, wired controls are shown: the file explorer
 * toggle, the terminal/logs toggle and the API Doctor panel toggle.
 */
export default function ActivityBar({
  isDoctorOpen,
  setIsDoctorOpen,
  isExplorerOpen,
  setIsExplorerOpen,
  hasActiveRun,
  onOpenTerminal,
}) {
  const items = [
    {
      id: 'explorer',
      label: 'Explorer',
      icon: FolderOpen,
      active: isExplorerOpen,
      action: () => setIsExplorerOpen(!isExplorerOpen),
    },
    { id: 'terminal', label: 'Terminal & logs', icon: SquareTerminal, action: onOpenTerminal },
    {
      id: 'doctor',
      label: 'API Doctor',
      icon: ShieldCheck,
      active: isDoctorOpen,
      action: () => setIsDoctorOpen(!isDoctorOpen),
      doctor: true,
    },
  ];

  return (
    <aside className="ide-activitybar">
      <div className="ide-activity-items">
        {items.map((item) => {
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
    </aside>
  );
}
