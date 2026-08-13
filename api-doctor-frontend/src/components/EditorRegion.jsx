import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Lock,
  FileCode,
  Columns,
  AlertTriangle,
  Check,
  X,
  Sparkles,
  XCircle
} from 'lucide-react';
import CodeEditor from './CodeEditor';

export default function EditorRegion({
  selectedFile,
  fileContent = '',
  runContext,
  runDiff,
  isDiagnosing,
  isDiffMode,
  setIsDiffMode,
  onApproveFix,
  highlightLine = null,
  failureReason = '',
  isProjectConnected = false,
  openFiles = [],
  onSelectTab,
  onCloseTab
}) {
  const [activeDiffPath, setActiveDiffPath] = useState('');
  const [calloutDismissed, setCalloutDismissed] = useState(false);
  const activeTabRef = useRef(null);

  // Keep the active tab visible when the strip overflows horizontally.
  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [selectedFile, openFiles.length]);

  const diffFiles = useMemo(
    () => (runDiff?.present && Array.isArray(runDiff.files) ? runDiff.files : []),
    [runDiff]
  );

  // Keep the selected diff file valid as the proposal changes.
  useEffect(() => {
    if (!diffFiles.length) {
      setActiveDiffPath('');
      return;
    }
    if (activeDiffPath && diffFiles.some(f => f.path === activeDiffPath)) return;
    const matchSelected = diffFiles.find(f => f.path === selectedFile);
    setActiveDiffPath((matchSelected || diffFiles[0]).path);
  }, [diffFiles, selectedFile, activeDiffPath]);

  // Re-show the failure callout when the file/error changes.
  useEffect(() => {
    setCalloutDismissed(false);
  }, [selectedFile, highlightLine]);

  // VS Code-style persistent tabs come from App state; while an older bundle
  // or edge path supplies none, fall back to showing just the current file.
  const openTabs = (openFiles.length ? openFiles : (selectedFile ? [selectedFile] : []))
    .map(path => ({
      path,
      name: path.split('/').pop(),
      isAgentActive: isDiagnosing && path === selectedFile
    }));

  // Determine code to display: prioritize real fileContent from workspace,
  // then snippet from runContext.
  let rawCode = fileContent || '';
  let errorLine = highlightLine;

  if (!rawCode && runContext?.code_snippets?.[selectedFile]) {
    const snippet = runContext.code_snippets[selectedFile];
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
  const showDiff = isDiffMode && runDiff?.present && (diffFiles.length > 0 || runDiff.diff);
  const activeDiffFile = diffFiles.find(f => f.path === activeDiffPath) || null;
  const failureText = failureReason
    || (runContext?.stack_trace ? runContext.stack_trace.split('\n').pop() : '');

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
        <div className="tabstrip" role="tablist" aria-label="Open files">
          {openTabs.map(tab => {
            const isActive = selectedFile === tab.path;
            return (
              <div
                key={tab.path}
                role="tab"
                aria-selected={isActive}
                tabIndex={0}
                ref={isActive ? activeTabRef : undefined}
                className={`tabstrip-tab${isActive ? ' is-active' : ''}`}
                title={tab.path}
                onClick={() => onSelectTab ? onSelectTab(tab.path) : undefined}
                onMouseDown={(e) => {
                  // VS Code: middle-click a tab closes it.
                  if (e.button === 1 && onCloseTab) {
                    e.preventDefault();
                    onCloseTab(tab.path);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectTab?.(tab.path);
                  } else if (e.key === 'Delete' && onCloseTab) {
                    e.preventDefault();
                    onCloseTab(tab.path);
                  }
                }}
              >
                <FileCode size={13} style={{ color: '#3572A5', flexShrink: 0 }} />
                <span className="tabstrip-name">{tab.name}</span>
                {tab.isAgentActive && <span className="agent-dot" style={{ width: '6px', height: '6px', flexShrink: 0 }} />}
                <button
                  type="button"
                  className="tabstrip-close"
                  title={`Close ${tab.name}`}
                  aria-label={`Close ${tab.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onCloseTab?.(tab.path);
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <X size={12} />
                </button>
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {runDiff && runDiff.present && (
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

      {selectedFile && (
        <div className="ide-breadcrumb">
          {selectedFile.split('/').map((part, index, parts) => (
            <React.Fragment key={`${part}-${index}`}>
              <span className={index === parts.length - 1 ? 'is-file' : ''}>{part}</span>
              {index < parts.length - 1 && <b>›</b>}
            </React.Fragment>
          ))}
        </div>
      )}

      {/* Read-Only Banner when agent is diagnosing */}
      {isDiagnosing && !showDiff && (
        <div style={{
          backgroundColor: 'rgba(240, 169, 58, 0.10)',
          borderBottom: '1px solid rgba(240, 169, 58, 0.3)',
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

      {/* Editor Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {showDiff ? (
          /* SIDE-BY-SIDE DIFF VIEW (Monaco diff editor) */
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
            <div style={{
              padding: '6px 12px',
              backgroundColor: 'var(--surface-2)',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 600, minWidth: 0 }}>
                <Sparkles size={13} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  AI Proposed Fix: {runDiff.summary || 'Proposed Patch'}
                </span>
              </div>

              {onApproveFix && !runDiff.applied && (
                <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
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
              {runDiff.applied && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--color-success)', fontWeight: 600, flexShrink: 0 }}>
                  <Check size={12} />
                  <span>Applied to workspace</span>
                </div>
              )}
            </div>

            {/* Per-file tabs when the patch touches several files */}
            {diffFiles.length > 1 && (
              <div style={{ display: 'flex', backgroundColor: 'var(--surface-1)', borderBottom: '1px solid var(--border-color)' }}>
                {diffFiles.map(f => (
                  <div
                    key={f.path}
                    onClick={() => setActiveDiffPath(f.path)}
                    style={{
                      padding: '5px 12px',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer',
                      color: activeDiffPath === f.path ? 'var(--text-primary)' : 'var(--text-muted)',
                      backgroundColor: activeDiffPath === f.path ? 'var(--bg-canvas)' : 'transparent',
                      borderRight: '1px solid var(--border-color)',
                      borderBottom: activeDiffPath === f.path ? '2px solid var(--color-accent)' : '2px solid transparent'
                    }}
                  >
                    {f.path}
                    {f.error && <XCircle size={10} style={{ color: 'var(--color-failure)', marginLeft: '5px', verticalAlign: 'middle' }} />}
                  </div>
                ))}
              </div>
            )}

            {activeDiffFile?.error && (
              <div style={{
                padding: '6px 12px',
                backgroundColor: 'rgba(244, 63, 94, 0.10)',
                borderBottom: '1px solid rgba(244, 63, 94, 0.3)',
                color: 'var(--color-failure)',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)'
              }}>
                {activeDiffFile.error}
              </div>
            )}

            <div style={{ flex: 1, minHeight: 0 }}>
              {activeDiffFile ? (
                <CodeEditor
                  mode="diff"
                  original={activeDiffFile.original}
                  modified={activeDiffFile.proposed}
                  path={activeDiffFile.path}
                  modifiedPath={activeDiffFile.path}
                />
              ) : (
                /* Fallback: raw unified diff text if previews are unavailable */
                <div style={{ height: '100%', overflowY: 'auto', padding: '12px', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  <pre style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {(runDiff.diff || '').split('\n').map((line, idx) => {
                      let bg = 'transparent';
                      let color = 'var(--text-primary)';
                      if (line.startsWith('+') && !line.startsWith('+++')) {
                        bg = 'var(--diff-add-bg)';
                        color = 'var(--diff-add-text)';
                      } else if (line.startsWith('-') && !line.startsWith('---')) {
                        bg = 'var(--diff-remove-bg)';
                        color = 'var(--diff-remove-text)';
                      } else if (line.startsWith('@@')) {
                        color = 'var(--color-accent)';
                      }
                      return (
                        <div key={idx} style={{ backgroundColor: bg, color, padding: '0 6px', borderRadius: '2px' }}>
                          {line}
                        </div>
                      );
                    })}
                  </pre>
                </div>
              )}
            </div>
          </div>
        ) : (
          /* STANDARD CODE VIEW — real Monaco editor with syntax highlighting */
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, position: 'relative' }}>
            {showConnectEmpty ? (
              <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
                  Connect a GitHub repository
                </div>
                <div style={{ fontSize: '12px', lineHeight: 1.5 }}>
                  Synchronize a real project to browse its source tree and start diagnosis.
                </div>
              </div>
            ) : selectedFile ? (
              <CodeEditor
                mode="view"
                value={rawCode}
                path={selectedFile}
                highlightLine={errorLine}
              />
            ) : (
              <div style={{ padding: '48px 24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                Select a file from the explorer to view its contents.
              </div>
            )}

            {/* Inline Failure Callout Card */}
            {errorLine !== null && !calloutDismissed && !showConnectEmpty && selectedFile && (
              <div style={{
                position: 'absolute',
                top: '12px',
                right: '70px',
                maxWidth: '460px',
                backgroundColor: 'var(--surface-1)',
                border: '1px solid var(--color-accent)',
                borderRadius: '6px',
                padding: '10px 14px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                zIndex: 5
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 600, fontSize: '11px' }}>
                    <AlertTriangle size={14} />
                    <span>SUSPECTED FAILURE ON LINE {errorLine}</span>
                  </div>
                  <button
                    onClick={() => setCalloutDismissed(true)}
                    style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                  >
                    <X size={12} />
                  </button>
                </div>
                {failureText && (
                  <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '4px', fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>
                    {failureText}
                  </p>
                )}
                {runContext?.root_cause?.reason && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {runContext.root_cause.reason}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
