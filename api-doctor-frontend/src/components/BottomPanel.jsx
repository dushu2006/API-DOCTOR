import React, { useState } from 'react';
import { 
  Terminal, 
  FileText, 
  ListFilter, 
  FileDiff, 
  CheckCircle2, 
  ChevronDown, 
  ChevronUp, 
  Copy,
  Search,
  Check,
  XCircle
} from 'lucide-react';

export default function BottomPanel({ 
  activeIncident,
  incidentContext,
  incidentDiff,
  incidentSandbox,
  activeBottomTab, 
  setActiveBottomTab,
  bottomHeight = 220,
  isBottomCollapsed,
  setIsBottomCollapsed
}) {
  const [copied, setCopied] = useState(false);
  const [logFilter, setLogFilter] = useState('');

  const tabs = [
    { id: 'terminal', label: 'Terminal', icon: Terminal },
    { id: 'output', label: 'Output', icon: FileText },
    { id: 'logs', label: 'Logs', icon: ListFilter, badge: activeIncident ? activeIncident.status : null },
    { id: 'diff', label: 'Diff', icon: FileDiff, badge: incidentDiff?.present ? 'PATCH' : null },
    { id: 'tests', label: 'Tests', icon: CheckCircle2, badge: incidentSandbox?.present ? (incidentSandbox.passed ? 'PASSED' : 'FAILED') : null },
  ];

  const handleCopyDiff = () => {
    if (incidentDiff?.diff) {
      navigator.clipboard.writeText(incidentDiff.diff);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (isBottomCollapsed) {
    return (
      <div style={{
        height: '32px',
        backgroundColor: 'var(--surface-1)',
        borderTop: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        userSelect: 'none'
      }}>
        <div style={{ display: 'flex', gap: '16px' }}>
          {tabs.map(t => (
            <div 
              key={t.id} 
              onClick={() => { setActiveBottomTab(t.id); setIsBottomCollapsed(false); }}
              style={{ fontSize: '11px', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <span>{t.label}</span>
            </div>
          ))}
        </div>
        <button onClick={() => setIsBottomCollapsed(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <ChevronUp size={14} />
        </button>
      </div>
    );
  }

  return (
    <div style={{
      height: `${bottomHeight}px`,
      backgroundColor: 'var(--surface-1)',
      borderTop: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      userSelect: 'none',
      zIndex: 20
    }}>
      {/* Header & Tabs */}
      <div style={{
        height: '32px',
        backgroundColor: 'var(--surface-2)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px'
      }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {tabs.map(t => {
            const Icon = t.icon;
            const isActive = activeBottomTab === t.id;
            return (
              <div 
                key={t.id}
                onClick={() => setActiveBottomTab(t.id)}
                style={{
                  height: '100%',
                  padding: '0 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: isActive ? 'var(--surface-1)' : 'transparent',
                  borderTop: isActive ? '2px solid var(--color-accent)' : '2px solid transparent',
                  cursor: 'pointer',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
                  fontSize: '11px',
                  fontWeight: 500
                }}
              >
                <Icon size={13} />
                <span>{t.label}</span>
                {t.badge && (
                  <span style={{ 
                    fontSize: '9px', 
                    padding: '1px 4px', 
                    borderRadius: '3px', 
                    backgroundColor: t.badge.includes('FAIL') ? 'rgba(240,96,90,0.2)' : 'rgba(61,214,140,0.2)',
                    color: t.badge.includes('FAIL') ? 'var(--color-failure)' : 'var(--color-success)'
                  }}>
                    {t.badge}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button onClick={() => setIsBottomCollapsed(true)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* Tab Content Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
        
        {/* Terminal Tab */}
        {activeBottomTab === 'terminal' && (
          <div style={{ color: 'var(--text-primary)', lineHeight: 1.6 }}>
            <div style={{ color: 'var(--text-muted)' }}>[WORKSPACE] API Doctor Diagnostic Environment</div>
            <div>[STATUS] Connected to backend service.</div>
            {activeIncident ? (
              <div style={{ color: 'var(--color-accent)', marginTop: '4px' }}>
                [ACTIVE] Incident #{activeIncident.id.slice(0, 8)} ({activeIncident.status})
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', marginTop: '4px' }}>
                [READY] Select an incident or ingest production logs to begin diagnosis.
              </div>
            )}
          </div>
        )}

        {/* Output Tab */}
        {activeBottomTab === 'output' && (
          <div style={{ color: 'var(--text-primary)', lineHeight: 1.6 }}>
            {activeIncident ? (
              <>
                <div>[{new Date(activeIncident.created_at).toLocaleTimeString()}] [INFO] Incident #{activeIncident.id.slice(0, 8)} ({activeIncident.detection?.source || 'production'})</div>
                <div>[{new Date(activeIncident.updated_at).toLocaleTimeString()}] [STATUS] Current stage: {activeIncident.status}</div>
                {incidentContext?.stack_trace && (
                  <div style={{ color: 'var(--color-failure)', marginTop: '4px' }}>
                    [ERROR] {incidentContext.stack_trace.split('\n')[0]}
                  </div>
                )}
              </>
            ) : (
              <div style={{ color: 'var(--text-muted)' }}>No active incident output.</div>
            )}
          </div>
        )}

        {/* Logs Tab */}
        {activeBottomTab === 'logs' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', backgroundColor: 'var(--surface-2)', padding: '2px 8px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                <Search size={12} style={{ color: 'var(--text-muted)' }} />
                <input 
                  type="text" 
                  placeholder="Filter runtime logs..."
                  value={logFilter}
                  onChange={e => setLogFilter(e.target.value)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-primary)', fontSize: '11px', outline: 'none' }}
                />
              </div>
            </div>

            {incidentContext && incidentContext.stack_trace ? (
              <pre style={{ whiteSpace: 'pre-wrap', color: 'var(--color-failure)', fontSize: '11px' }}>
                {incidentContext.stack_trace}
              </pre>
            ) : (
              <div style={{ color: 'var(--text-muted)' }}>No exception logs captured for this incident.</div>
            )}
          </div>
        )}

        {/* Diff Tab */}
        {activeBottomTab === 'diff' && (
          <div style={{ position: 'relative' }}>
            {incidentDiff && incidentDiff.diff ? (
              <>
                <button 
                  onClick={handleCopyDiff}
                  style={{
                    position: 'absolute',
                    top: 0,
                    right: 0,
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '10px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}
                >
                  {copied ? <Check size={12} style={{ color: 'var(--color-success)' }} /> : <Copy size={12} />}
                  <span>{copied ? 'Copied!' : 'Copy Patch'}</span>
                </button>

                <pre style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, marginTop: '20px' }}>
                  {incidentDiff.diff.split('\n').map((line, idx) => {
                    let bg = 'transparent';
                    let color = 'var(--text-primary)';
                    if (line.startsWith('+') && !line.startsWith('+++')) {
                      bg = 'var(--diff-add-bg)';
                      color = 'var(--diff-add-text)';
                    } else if (line.startsWith('-') && !line.startsWith('---')) {
                      bg = 'var(--diff-remove-bg)';
                      color = 'var(--diff-remove-text)';
                    }
                    return (
                      <div key={idx} style={{ backgroundColor: bg, color: color, padding: '0 4px' }}>
                        {line}
                      </div>
                    );
                  })}
                </pre>
              </>
            ) : (
              <div style={{ color: 'var(--text-muted)' }}>No diff patch generated yet.</div>
            )}
          </div>
        )}

        {/* Tests Tab */}
        {activeBottomTab === 'tests' && (
          <div>
            {incidentSandbox && incidentSandbox.present ? (
              <div>
                <div style={{ marginBottom: '10px', color: incidentSandbox.passed ? 'var(--color-success)' : 'var(--color-failure)', fontWeight: 600 }}>
                  Sandbox Result: {incidentSandbox.passed ? 'PASSED' : 'FAILED'}
                </div>
                {incidentSandbox.steps && incidentSandbox.steps.map((st, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '4px 8px', backgroundColor: 'var(--surface-2)', borderRadius: '4px', marginBottom: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {st.passed
                        ? <CheckCircle2 size={13} style={{ color: 'var(--color-success)' }} />
                        : <XCircle size={13} style={{ color: 'var(--color-failure)' }} />}
                      <span>{st.name || st.step || `Step ${i + 1}`}</span>
                    </div>
                    <span title={st.detail || ''} style={{ color: st.passed ? 'var(--color-success)' : 'var(--color-failure)' }}>
                      {st.passed ? 'PASSED' : 'FAILED'}
                    </span>
                  </div>
                ))}
                {incidentSandbox.logs && (
                  <pre style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '10px' }}>
                    {incidentSandbox.logs}
                  </pre>
                )}
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)' }}>No verification test results recorded yet.</div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
