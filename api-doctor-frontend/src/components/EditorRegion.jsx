import React, { useEffect, useRef } from 'react';
import {
  Lock,
  FileCode,
  Columns,
  AlertTriangle,
  Check,
  X,
  Sparkles
} from 'lucide-react';

export default function EditorRegion({
  selectedFile,
  fileContent = '',
  incidentContext,
  incidentDiff,
  isDiagnosing,
  isDiffMode,
  setIsDiffMode,
  onApproveFix,
  highlightLine = null,
  failureReason = '',
  isProjectConnected = false
}) {
  const lineRefs = useRef({});
  const editorContainerRef = useRef(null);

  const openTabs = selectedFile ? [
    { 
      path: selectedFile, 
      name: selectedFile.split('/').pop(), 
      isAgentActive: isDiagnosing 
    },
  ] : [];

  // Determine code to display: prioritize real fileContent from workspace,
  // then snippet from incidentContext.
  let rawCode = fileContent || '';
  let errorLine = highlightLine;

  if (!rawCode && incidentContext?.code_snippets?.[selectedFile]) {
    const snippet = incidentContext.code_snippets[selectedFile];
    if (typeof snippet === 'string') {
      rawCode = snippet;
    } else if (snippet && typeof snippet === 'object') {
      if (errorLine === null && snippet.error_line !== undefined) {
        errorLine = snippet.error_line;
      }
      if (typeof snippet.content === 'string') rawCode = snippet.content;
      else if (typeof snippet.code === 'string') rawCode = snippet.code;
      else if (Array.isArray(snippet.lines)) rawCode = snippet.lines.join('\n');
    }
  }

  const showConnectEmpty = !isProjectConnected && !rawCode;
  if (!rawCode && isProjectConnected) {
    rawCode = `# ${selectedFile || 'Project Workspace'}\n# Select a file from the explorer to view its contents.`;
  }

  const lines = rawCode.split('\n').map((rawLine, index) => {
    const numbered = rawLine.match(/^\s*(\d+)\s+\|\s?(.*)$/);
    return numbered
      ? { number: Number(numbered[1]), text: numbered[2] }
      : { number: index + 1, text: rawLine };
  });

  // Auto-scroll to error line when selected
  useEffect(() => {
    if (errorLine && lineRefs.current[errorLine] && editorContainerRef.current) {
      lineRefs.current[errorLine].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [errorLine, selectedFile]);

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
        justifyContent: 'space-between',
        paddingRight: '12px'
      }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {openTabs.map(tab => {
            const isActive = selectedFile === tab.path || (!selectedFile && tab.name === 'README.md');
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

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {incidentDiff && incidentDiff.present && (
            <button 
              onClick={() => setIsDiffMode(!isDiffMode)}
              className="btn-outline"
              style={{ padding: '3px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Columns size={12} />
              <span>{isDiffMode ? 'Standard Code View' : 'Split View: Before / After Diff'}</span>
            </button>
          )}
        </div>
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
          <span>Read-only — API Doctor agent is analyzing project repository</span>
        </div>
      )}

      {/* Code Editor Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {isDiffMode && incidentDiff && incidentDiff.diff ? (
          /* SPLIT / UNIFIED DIFF VIEW FROM BACKEND */
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
            <div style={{
              padding: '6px 12px',
              backgroundColor: 'var(--surface-2)',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 600 }}>
                <Sparkles size={13} />
                <span>AI Proposed Fix: {incidentDiff.summary || 'Verified Patch'}</span>
              </div>

              {onApproveFix && (
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button 
                    onClick={() => onApproveFix(true)}
                    className="btn-success"
                    style={{ padding: '2px 8px', fontSize: '11px' }}
                  >
                    <Check size={11} />
                    <span>Keep Changes</span>
                  </button>
                  <button 
                    onClick={() => onApproveFix(false)}
                    className="btn-outline"
                    style={{ padding: '2px 8px', fontSize: '11px' }}
                  >
                    <X size={11} />
                    <span>Reject</span>
                  </button>
                </div>
              )}
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '12px', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <pre style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                {incidentDiff.diff.split('\n').map((line, idx) => {
                  let bg = 'transparent';
                  let color = 'var(--text-primary)';
                  if (line.startsWith('+') && !line.startsWith('+++')) {
                    bg = 'rgba(61, 214, 140, 0.15)';
                    color = '#3dd68c';
                  } else if (line.startsWith('-') && !line.startsWith('---')) {
                    bg = 'rgba(240, 96, 90, 0.15)';
                    color = '#f0605a';
                  } else if (line.startsWith('@@')) {
                    color = 'var(--color-accent)';
                  }
                  return (
                    <div key={idx} style={{ backgroundColor: bg, color: color, padding: '0 6px', borderRadius: '2px' }}>
                      {line}
                    </div>
                  );
                })}
              </pre>
            </div>
          </div>
        ) : (
          /* STANDARD CODE VIEW WITH REAL STACK TRACE FAILURE CALLOUT */
          <div ref={editorContainerRef} style={{ flex: 1, overflowY: 'auto', padding: '12px 0' }}>
            {showConnectEmpty ? (
              <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
                  Connect a GitHub repository
                </div>
                <div style={{ fontSize: '12px', lineHeight: 1.5 }}>
                  Synchronize a real project to browse its source tree and start diagnosis.
                </div>
              </div>
            ) : lines.map((line, idx) => {
              const lineNum = line.number;
              const lineText = line.text;
              const isFailureLine = errorLine !== null && lineNum === errorLine;
              return (
                <React.Fragment key={idx}>
                  <div 
                    ref={el => { if (el && isFailureLine) lineRefs.current[lineNum] = el; }}
                    style={{
                      display: 'flex',
                      lineHeight: '22px',
                      backgroundColor: isFailureLine ? 'rgba(124, 140, 248, 0.15)' : 'transparent',
                      borderLeft: isFailureLine ? '3px solid var(--color-accent)' : '3px solid transparent',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ width: '50px', textAlign: 'right', paddingRight: '14px', color: isFailureLine ? 'var(--color-accent)' : 'var(--text-muted)', userSelect: 'none', fontWeight: isFailureLine ? 700 : 400 }}>
                      {lineNum}
                    </div>
                    <div style={{ flex: 1, paddingLeft: '8px', whiteSpace: 'pre', color: isFailureLine ? '#ffffff' : 'inherit' }}>
                      {lineText}
                    </div>
                  </div>

                  {/* Inline Failure Callout Card */}
                  {isFailureLine && (
                    <div style={{
                      margin: '8px 16px 12px 55px',
                      maxWidth: '600px',
                      backgroundColor: 'var(--surface-1)',
                      border: '1px solid var(--color-accent)',
                      borderRadius: '6px',
                      padding: '10px 14px',
                      boxShadow: '0 4px 12px rgba(0,0,0,0.4)'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 600, fontSize: '11px' }}>
                          <AlertTriangle size={14} />
                          <span>SUSPECTED FAILURE DETECTED ON LINE {lineNum}</span>
                        </div>
                      </div>
                      <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>
                        {failureReason || (incidentContext?.stack_trace ? incidentContext.stack_trace.split('\n').pop() : "Exception occurred at this location")}
                      </p>
                      {incidentContext?.root_cause?.reason && (
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                          {incidentContext.root_cause.reason}
                        </p>
                      )}
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
