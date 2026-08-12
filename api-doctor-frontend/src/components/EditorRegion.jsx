import React from 'react';
import {
  Lock,
  FileCode,
  Columns,
  AlertTriangle 
} from 'lucide-react';

export default function EditorRegion({
  selectedFile,
  incidentContext,
  incidentDiff,
  isDiagnosing,
  isDiffMode,
  setIsDiffMode
}) {
  const openTabs = [
    { path: selectedFile || 'app/demo_api/bugs.py', name: selectedFile ? selectedFile.split('/').pop() : 'bugs.py', isAgentActive: isDiagnosing },
  ];

  // Context snippets are the only source shown in the editor. Never substitute
  // another file or a fabricated sample under the selected filename.
  const snippet = incidentContext?.code_snippets?.[selectedFile];
  let rawCode = '';
  let errorLine = null;
  if (typeof snippet === 'string') {
    rawCode = snippet;
  } else if (snippet && typeof snippet === 'object') {
    errorLine = snippet.error_line ?? null;
    if (typeof snippet.content === 'string') rawCode = snippet.content;
    else if (typeof snippet.code === 'string') rawCode = snippet.code;
    else if (Array.isArray(snippet.lines)) rawCode = snippet.lines.join('\n');
  }
  if (!rawCode) {
    rawCode = `# No retrieved source snippet is available for ${selectedFile}.\n# Select an implicated file after context collection completes.`;
  }

  const lines = rawCode.split('\n').map((rawLine, index) => {
    const numbered = rawLine.match(/^\s*(\d+)\s+\|\s?(.*)$/);
    return numbered
      ? { number: Number(numbered[1]), text: numbered[2] }
      : { number: index + 1, text: rawLine };
  });

  return (
    <div style={{
      flex: 1,
      height: '100%',
      backgroundColor: 'var(--bg-canvas)',
      display: 'flex',
      flexDirection: 'column',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Tab Bar */}
      <div style={{
        height: '35px',
        backgroundColor: 'var(--surface-1)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justify: 'space-between',
        paddingRight: '12px'
      }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {openTabs.map(tab => {
            const isActive = selectedFile === tab.path;
            return (
              <div 
                key={tab.path}
                style={{
                  height: '100%',
                  padding: '0 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  backgroundColor: isActive ? 'var(--bg-canvas)' : 'transparent',
                  borderRight: '1px solid var(--border-color)',
                  borderBottom: isActive 
                    ? (tab.isAgentActive ? '2px solid var(--color-accent)' : '2px solid #ffffff') 
                    : 'none',
                  cursor: 'pointer',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)'
                }}
              >
                <FileCode size={13} style={{ color: '#3572A5' }} />
                <span>{tab.name}</span>
                {tab.isAgentActive && <span className="agent-dot" style={{ width: '6px', height: '6px' }} />}
              </div>
            );
          })}
        </div>

        {incidentDiff && incidentDiff.present && (
          <button 
            onClick={() => setIsDiffMode(!isDiffMode)}
            className="btn-outline"
            style={{ padding: '3px 8px', fontSize: '11px' }}
          >
            <Columns size={12} />
            <span>{isDiffMode ? 'Unified Code' : 'Split View: Before / After'}</span>
          </button>
        )}
      </div>

      {/* Read-Only Banner when agent is diagnosing */}
      {isDiagnosing && (
        <div style={{
          backgroundColor: 'rgba(124, 140, 248, 0.15)',
          borderBottom: '1px solid rgba(124, 140, 248, 0.3)',
          padding: '4px 16px',
          fontSize: '11px',
          color: 'var(--color-accent)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-mono)'
        }}>
          <Lock size={12} />
          <span>Read-only — API Doctor agent is analyzing workspace code</span>
        </div>
      )}

      {/* Code Editor Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {isDiffMode && incidentDiff && incidentDiff.diff ? (
          /* SPLIT / UNIFIED DIFF VIEW FROM BACKEND */
          <div style={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <div style={{ flex: 1, borderRight: '1px solid var(--border-color)', overflowY: 'auto', padding: '12px', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <div style={{ padding: '4px 12px', fontSize: '11px', color: 'var(--color-accent)', fontWeight: 600, borderBottom: '1px solid var(--border-color)', marginBottom: '8px' }}>
                Backend Generated Patch ({incidentDiff.summary})
              </div>
              <pre style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                {incidentDiff.diff.split('\n').map((line, idx) => {
                  let bg = 'transparent';
                  let color = 'var(--text-primary)';
                  if (line.startsWith('+')) {
                    bg = 'var(--diff-add-bg)';
                    color = 'var(--diff-add-text)';
                  } else if (line.startsWith('-')) {
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
            </div>
          </div>
        ) : (
          /* STANDARD CODE VIEW WITH REAL STACK TRACE FAILURE CALLOUT */
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 0' }}>
            {lines.map((line, idx) => {
              const lineNum = line.number;
              const lineText = line.text;
              const isFailureLine = errorLine !== null && lineNum === errorLine;
              return (
                <React.Fragment key={idx}>
                  <div 
                    style={{
                      display: 'flex',
                      lineHeight: '22px',
                      backgroundColor: isFailureLine ? 'rgba(124, 140, 248, 0.15)' : 'transparent',
                      borderLeft: isFailureLine ? '3px solid var(--color-accent)' : '3px solid transparent',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ width: '50px', textAlign: 'right', paddingRight: '14px', color: 'var(--text-muted)', userSelect: 'none' }}>
                      {lineNum}
                    </div>
                    <div style={{ flex: 1, paddingLeft: '8px', whiteSpace: 'pre' }}>
                      {lineText}
                    </div>
                  </div>

                  {/* Inline Failure Callout Card */}
                  {isFailureLine && incidentContext && (
                    <div style={{
                      margin: '8px 16px 12px 55px',
                      maxWidth: '560px',
                      backgroundColor: 'var(--surface-1)',
                      border: '1px solid var(--color-accent)',
                      borderRadius: '6px',
                      padding: '10px 14px',
                      boxShadow: '0 4px 12px rgba(0,0,0,0.4)'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 600, fontSize: '11px' }}>
                          <AlertTriangle size={14} />
                          <span>SUSPECTED FAILURE DETECTED</span>
                        </div>
                      </div>
                      <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>
                        {incidentContext.stack_trace ? incidentContext.stack_trace.split('\n').pop() : "AttributeError: 'NoneType' object has no attribute 'token'"}
                      </p>
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}

        {/* Minimap */}
        <div style={{
          width: '50px',
          height: '100%',
          backgroundColor: 'var(--surface-1)',
          borderLeft: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: '20px',
          opacity: 0.6
        }}>
          <div style={{ width: '30px', height: '3px', backgroundColor: 'var(--border-color)', marginBottom: '4px' }} />
          <div style={{ width: '25px', height: '3px', backgroundColor: 'var(--border-color)', marginBottom: '4px' }} />
          <div style={{ width: '35px', height: '3px', backgroundColor: 'var(--color-accent)', marginBottom: '4px' }} />
          <div style={{ width: '20px', height: '3px', backgroundColor: 'var(--border-color)', marginBottom: '4px' }} />
        </div>
      </div>
    </div>
  );
}
