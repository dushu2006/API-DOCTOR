import React, { useState } from 'react';
import {
  FolderTree,
  Stethoscope
} from 'lucide-react';

export default function ActivityBar({
  isDoctorOpen,
  setIsDoctorOpen,
  isExplorerOpen,
  setIsExplorerOpen,
  hasActiveIncident
}) {
  const [hoveredIcon, setHoveredIcon] = useState(null);

  // Only render controls backed by a real panel. This avoids presenting
  // placeholder Search/SCM/Test/Extensions buttons as working features.
  const topItems = [
    { id: 'explorer', label: 'Explorer', shortcut: '⌘⇧E', icon: FolderTree, toggle: () => setIsExplorerOpen(!isExplorerOpen), active: isExplorerOpen },
    { id: 'doctor', label: 'API Doctor', shortcut: '⌘⇧D', icon: Stethoscope, isHero: true, toggle: () => setIsDoctorOpen(!isDoctorOpen), active: isDoctorOpen },
  ];

  return (
    <aside style={{
      width: '48px',
      height: '100%',
      backgroundColor: 'var(--surface-1)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'flex-start',
      alignItems: 'center',
      padding: '8px 0',
      zIndex: 40,
      userSelect: 'none'
    }}>
      {/* Top Icons */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', width: '100%' }}>
        {topItems.map((item) => {
          const Icon = item.icon;
          const isHovered = hoveredIcon === item.id;
          return (
            <div 
              key={item.id}
              style={{ position: 'relative', width: '100%', display: 'flex', justifyContent: 'center' }}
              onMouseEnter={() => setHoveredIcon(item.id)}
              onMouseLeave={() => setHoveredIcon(null)}
            >
              <button
                onClick={item.toggle}
                style={{
                  width: '100%',
                  height: '42px',
                  background: 'none',
                  border: 'none',
                  borderLeft: item.active ? '2px solid var(--color-accent)' : '2px solid transparent',
                  color: item.active ? 'var(--text-primary)' : 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  justify: 'center',
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'color 0.15s ease'
                }}
              >
                <Icon 
                  size={item.isHero ? 20 : 18} 
                  style={{ color: item.isHero && item.active ? 'var(--color-accent)' : undefined }}
                />
                
                {item.isHero && hasActiveIncident && (
                  <span style={{
                    position: 'absolute',
                    top: '8px',
                    right: '12px',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--color-accent)',
                    boxShadow: '0 0 6px var(--color-accent)'
                  }} />
                )}
              </button>

              {/* Tooltip */}
              {isHovered && (
                <div style={{
                  position: 'absolute',
                  left: '52px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  backgroundColor: 'var(--surface-2)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  whiteSpace: 'nowrap',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                  zIndex: 100,
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center'
                }}>
                  <span>{item.label}</span>
                  <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '10px' }}>
                    {item.shortcut}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>


    </aside>
  );
}
