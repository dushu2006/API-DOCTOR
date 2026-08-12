import React, { useState, useEffect } from 'react';
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
  Radio
} from 'lucide-react';
import { api } from '../api';

export default function TopBar({ 
  activeIncident, 
  onStartDiagnosis, 
  onStopDiagnosis, 
  isDiagnosing,
  isBackendConnected 
}) {
  const [showBranches, setShowBranches] = useState(false);
  const [showScenarioMenu, setShowScenarioMenu] = useState(false);
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [currentBranch, setCurrentBranch] = useState('main');

  const branches = ['main', 'feature/auth-refactor', 'fix/null-pointer', 'staging'];
  const scenarios = [
    { id: 'null_pointer', label: 'Null Pointer Dereference' },
    { id: 'external_api', label: 'External API Timeout' },
    { id: 'config', label: 'Missing Environment Config' },
    { id: 'schema', label: 'JSON Schema Mismatch' }
  ];

  const handleDiagnoseClick = () => {
    if (isDiagnosing) {
      setShowStopDialog(true);
    } else {
      setShowScenarioMenu(!showScenarioMenu);
    }
  };

  const selectScenario = (sc) => {
    setShowScenarioMenu(false);
    onStartDiagnosis(sc);
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
      justify: 'space-between',
      padding: '0 16px',
      position: 'relative',
      zIndex: 50
    }}>
      {/* Left section: Logo & Branch Breadcrumb */}
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
            justify: 'center',
            color: '#fff'
          }}>
            <Stethoscope size={14} />
          </div>
          <span style={{ fontFamily: 'var(--font-heading)', letterSpacing: '0.02em' }}>API DOCTOR</span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        {/* Branch Breadcrumb */}
        <div style={{ position: 'relative' }}>
          <button 
            onClick={() => setShowBranches(!showBranches)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '4px'
            }}
          >
            <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>API-DOCTOR</span>
            <span>/</span>
            <GitBranch size={13} style={{ color: 'var(--color-accent)' }} />
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{currentBranch}</span>
            <ChevronDown size={12} />
          </button>

          {showBranches && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: '4px',
              width: '180px',
              backgroundColor: 'var(--surface-2)',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              boxShadow: '0 8px 16px rgba(0,0,0,0.4)',
              padding: '6px 0',
              zIndex: 100
            }}>
              <div style={{ padding: '4px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>
                SWITCH BRANCH
              </div>
              {branches.map(b => (
                <div 
                  key={b}
                  onClick={() => { setCurrentBranch(b); setShowBranches(false); }}
                  style={{
                    padding: '6px 12px',
                    fontSize: '12px',
                    color: b === currentBranch ? 'var(--color-accent)' : 'var(--text-primary)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justify: 'space-between',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  <span>{b}</span>
                  {b === currentBranch && <CheckCircle2 size={12} />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Middle Section: Connection & Diagnosis Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Real Backend Connection status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
          <span style={{ 
            width: '6px', 
            height: '6px', 
            borderRadius: '50%', 
            backgroundColor: isBackendConnected ? 'var(--color-success)' : 'var(--color-failure)' 
          }} />
          <span>{isBackendConnected ? 'Connected (localhost:8000)' : 'Backend Disconnected'}</span>
        </div>

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
            <span style={{ fontWeight: 500 }}>Diagnosing Backend...</span>
          </div>
        )}

        {/* Main CTA */}
        <div style={{ position: 'relative' }}>
          <button 
            onClick={handleDiagnoseClick}
            className={isDiagnosing ? 'btn-danger-outline' : 'btn-primary'}
            style={{ minWidth: '100px', justifyContent: 'center' }}
          >
            {isDiagnosing ? (
              <>
                <OctagonAlert size={13} />
                <span>Stop</span>
              </>
            ) : (
              <>
                <Stethoscope size={13} />
                <span>Diagnose ▾</span>
              </>
            )}
          </button>

          {/* Scenario Trigger Selector */}
          {showScenarioMenu && (
            <div style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: '6px',
              width: '220px',
              backgroundColor: 'var(--surface-2)',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              boxShadow: '0 8px 16px rgba(0,0,0,0.5)',
              padding: '6px 0',
              zIndex: 100
            }}>
              <div style={{ padding: '4px 12px', fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>
                SELECT BACKEND SCENARIO
              </div>
              {scenarios.map(sc => (
                <div 
                  key={sc.id}
                  onClick={() => selectScenario(sc.id)}
                  style={{
                    padding: '8px 12px',
                    fontSize: '12px',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                  className="hover-bg"
                >
                  <Radio size={12} style={{ color: 'var(--color-accent)' }} />
                  <span>{sc.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Section: Git status, Settings, Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div 
          title="Source Control"
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
            {activeIncident ? `${activeIncident.id.slice(0, 7)}` : 'main'}
          </span>
        </div>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-color)' }} />

        <button 
          title="Settings (⌘,)" 
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
        >
          <Settings size={15} />
        </button>

        <div 
          title="Account Profile"
          style={{
            width: '26px',
            height: '26px',
            borderRadius: '50%',
            backgroundColor: 'var(--surface-2)',
            border: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            justify: 'center',
            cursor: 'pointer',
            color: 'var(--text-muted)'
          }}
        >
          <User size={14} />
        </div>
      </div>

      {/* Confirm Stop Micro-Dialog */}
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
          justify: 'center'
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
              Are you sure you want to stop this investigation? Progress will be saved to incident history.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => setShowStopDialog(false)} className="btn-outline">Cancel</button>
              <button onClick={confirmStop} className="btn-danger-outline">Stop Investigation</button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
