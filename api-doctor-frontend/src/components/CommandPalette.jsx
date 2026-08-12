import React, { useState, useEffect } from 'react';
import { Search, Stethoscope, Columns, Terminal, GitBranch, Play, X } from 'lucide-react';

export default function CommandPalette({ isOpen, onClose, setCurrentState, setIsDiffMode, setActiveBottomTab }) {
  const [query, setQuery] = useState('');

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
        else onClose(true);
      }
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const actions = [
    { id: 'diagnose', label: 'Start API Doctor Diagnosis', icon: Stethoscope, run: () => { if (setCurrentState) setCurrentState(); onClose(); } },
    { id: 'diff', label: 'Toggle Diff Split View', icon: Columns, run: () => { if (setIsDiffMode) setIsDiffMode(prev => !prev); onClose(); } },
    { id: 'terminal', label: 'Open Terminal Panel', icon: Terminal, run: () => { if (setActiveBottomTab) setActiveBottomTab('terminal'); onClose(); } },
    { id: 'tests', label: 'View Sandbox Test Results', icon: Play, run: () => { if (setActiveBottomTab) setActiveBottomTab('tests'); onClose(); } },
    { id: 'logs', label: 'View Runtime Exception Logs', icon: Terminal, run: () => { if (setActiveBottomTab) setActiveBottomTab('logs'); onClose(); } },
  ];

  const filtered = actions.filter(a => a.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.6)',
      backdropFilter: 'blur(2px)',
      zIndex: 1000,
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'center',
      paddingTop: '80px'
    }} onClick={onClose}>
      <div 
        onClick={e => e.stopPropagation()}
        style={{
          width: '520px',
          backgroundColor: 'var(--surface-1)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          boxShadow: '0 16px 32px rgba(0,0,0,0.6)',
          overflow: 'hidden'
        }}
      >
        {/* Input */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'var(--surface-2)'
        }}>
          <Search size={16} style={{ color: 'var(--color-accent)' }} />
          <input 
            type="text"
            autoFocus
            placeholder="Type a command or search actions... (⌘K)"
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '13px',
              outline: 'none',
              width: '100%',
              fontFamily: 'var(--font-ui)'
            }}
          />
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={16} />
          </button>
        </div>

        {/* List */}
        <div style={{ padding: '6px 0', maxHeight: '300px', overflowY: 'auto' }}>
          {filtered.map(action => {
            const Icon = action.icon;
            return (
              <div 
                key={action.id}
                onClick={action.run}
                style={{
                  padding: '10px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  cursor: 'pointer',
                  fontSize: '12px',
                  color: 'var(--text-primary)'
                }}
                className="hover-bg"
                onMouseEnter={e => e.currentTarget.style.backgroundColor = 'var(--surface-hover)'}
                onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
              >
                <Icon size={16} style={{ color: 'var(--color-accent)' }} />
                <span>{action.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
