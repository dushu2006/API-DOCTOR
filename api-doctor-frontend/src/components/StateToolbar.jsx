import React from 'react';
import { Command } from 'lucide-react';

export default function StateToolbar({ currentState, setCurrentState, onOpenCommandPalette }) {
  const states = [
    { id: 'idle', label: '1. Idle Workspace' },
    { id: 'diagnosing', label: '2. Active Investigation' },
    { id: 'fix_proposed', label: '3. Proposed Fix Review' },
    { id: 'verified_pr', label: '4. Verified + PR Open' }
  ];

  return (
    <div style={{
      position: 'fixed',
      bottom: '12px',
      left: '50%',
      transform: 'translateX(-50%)',
      backgroundColor: 'var(--surface-2)',
      border: '1px solid var(--border-color)',
      borderRadius: '20px',
      padding: '4px 12px',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
      zIndex: 500,
      userSelect: 'none'
    }}>
      <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--color-accent)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Stitch State Switcher:
      </span>
      {states.map(s => (
        <button
          key={s.id}
          onClick={() => setCurrentState(s.id)}
          style={{
            background: currentState === s.id ? 'var(--color-accent)' : 'transparent',
            color: currentState === s.id ? '#ffffff' : 'var(--text-muted)',
            border: 'none',
            padding: '3px 10px',
            borderRadius: '12px',
            fontSize: '11px',
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.15s ease'
          }}
        >
          {s.label}
        </button>
      ))}

      <div style={{ width: '1px', height: '14px', backgroundColor: 'var(--border-color)' }} />

      <button 
        onClick={onOpenCommandPalette}
        style={{
          background: 'transparent',
          border: 'none',
          color: 'var(--text-muted)',
          fontSize: '11px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '4px'
        }}
        title="Open Command Palette (⌘K)"
      >
        <Command size={12} />
        <span>⌘K</span>
      </button>
    </div>
  );
}
