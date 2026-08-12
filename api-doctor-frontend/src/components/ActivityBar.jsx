import React, { useState } from 'react';
import { 
  FolderTree, 
  Search, 
  GitPullRequest, 
  Stethoscope, 
  PlayCircle, 
  Blocks, 
  Settings 
} from 'lucide-react';

export default function ActivityBar({ 
  activeTab, 
  setActiveTab, 
  isDoctorOpen, 
  setIsDoctorOpen,
  isExplorerOpen,
  setIsExplorerOpen,
  hasActiveIncident
}) {
  const [hoveredIcon, setHoveredIcon] = useState(null);

  const topItems = [
    { id: 'explorer', label: 'Explorer', shortcut: '⌘⇧E', icon: FolderTree, toggle: () => setIsExplorerOpen(!isExplorerOpen), active: isExplorerOpen },
    { id: 'search', label: 'Search', shortcut: '⌘⇧F', icon: Search, toggle: () => setActiveTab('search'), active: activeTab === 'search' },
    { id: 'source', label: 'Source Control', shortcut: '⌘⇧G', icon: GitPullRequest, toggle: () => setActiveTab('source'), active: activeTab === 'source' },
    { id: 'doctor', label: 'API Doctor', shortcut: '⌘⇧D', icon: Stethoscope, isHero: true, toggle: () => setIsDoctorOpen(!isDoctorOpen), active: isDoctorOpen },
    { id: 'testing', label: 'Run & Test', shortcut: '⌘⇧T', icon: PlayCircle, toggle: () => setActiveTab('testing'), active: activeTab === 'testing' },
    { id: 'extensions', label: 'Extensions', shortcut: '⌘⇧X', icon: Blocks, toggle: () => setActiveTab('extensions'), active: activeTab === 'extensions' },
  ];

  return (
    <aside style={{
      width: '48px',
      height: '100%',
      backgroundColor: 'var(--surface-1)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      justify: 'space-between',
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

      {/* Bottom Settings Icon */}
      <div 
        style={{ position: 'relative', width: '100%', display: 'flex', justifyContent: 'center' }}
        onMouseEnter={() => setHoveredIcon('settings')}
        onMouseLeave={() => setHoveredIcon(null)}
      >
        <button
          style={{
            width: '100%',
            height: '42px',
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            justify: 'center',
            cursor: 'pointer'
          }}
        >
          <Settings size={18} />
        </button>

        {hoveredIcon === 'settings' && (
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
            zIndex: 100
          }}>
            Settings
          </div>
        )}
      </div>
    </aside>
  );
}
