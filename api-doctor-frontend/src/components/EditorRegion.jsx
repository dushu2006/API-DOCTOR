import React, { useState } from 'react';
import { 
  X, 
  Lock, 
  FileCode, 
  FileText, 
  FileLock, 
  Search, 
  Columns, 
  FileDiff,
  AlertTriangle,
  ArrowUp,
  ArrowDown
} from 'lucide-react';

export default function EditorRegion({ 
  selectedFile, 
  setSelectedFile, 
  currentState, 
  isDiffMode,
  setIsDiffMode
}) {
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [gotoLine, setGotoLine] = useState('');
  const [showGoto, setShowGoto] = useState(false);

  const openTabs = [
    { path: 'app/demo_api/bugs.py', name: 'bugs.py', ext: 'py', isAgentActive: currentState === 'diagnosing' },
    { path: 'README.md', name: 'README.md', ext: 'md' },
  ];

  const getIcon = (ext) => {
    switch(ext) {
      case 'py': return <FileCode size={13} style={{ color: '#3572A5' }} />;
      case 'env': return <FileLock size={13} style={{ color: '#E8A23D' }} />;
      case 'md': return <FileText size={13} style={{ color: '#7C8CF8' }} />;
      default: return <FileText size={13} style={{ color: 'var(--text-muted)' }} />;
    }
  };

  const bugsOriginalCode = [
    { line: 115, code: 'def process_checkout(request_data):' },
    { line: 116, code: '    """Process API checkout order and validate payload"""' },
    { line: 117, code: '    user_id = request_data.get("user_id")' },
    { line: 118, code: '    order_amount = request_data.get("amount")' },
    { line: 119, code: '    payment_method = request_data.get("payment_method")' },
    { line: 120, code: '' },
    { line: 121, code: '    # Issue: payment_method can be NoneType when missing from request' },
    { line: 122, code: '    payment_token = payment_method.token  # UNSAFE ACCESS', isFailure: true },
    { line: 123, code: '    ' },
    { line: 124, code: '    logger.info(f"Processing order for user {user_id} with token {payment_token}")' },
    { line: 125, code: '    return {"status": "success", "token": payment_token}' },
  ];

  const bugsProposedCode = [
    { line: 115, code: 'def process_checkout(request_data):' },
    { line: 116, code: '    """Process API checkout order and validate payload"""' },
    { line: 117, code: '    user_id = request_data.get("user_id")' },
    { line: 118, code: '    order_amount = request_data.get("amount")' },
    { line: 119, code: '    payment_method = request_data.get("payment_method")' },
    { line: 120, code: '' },
    { line: 121, code: '    # FIXED: Added null safety verification' },
    { line: 122, code: '    if not payment_method:', type: 'add' },
    { line: 123, code: '        raise ValueError("Missing payment method payload")', type: 'add' },
    { line: 124, code: '    payment_token = payment_method.token', type: 'add' },
    { line: 125, code: '    ' },
    { line: 126, code: '    logger.info(f"Processing order for user {user_id} with token {payment_token}")' },
    { line: 127, code: '    return {"status": "success", "token": payment_token}' },
  ];

  const renderSyntaxHighlighted = (code) => {
    return code
      .replace(/(def|return|if|not|raise|import|from)/g, '<span style="color:#7C8CF8;font-weight:500;">$1</span>')
      .replace(/(".*?"|'.*? me.*?'|'.*?')/g, '<span style="color:#3DD68C;">$1</span>')
      .replace(/(#.*)/g, '<span style="color:#8B8D93;font-style:italic;">$1</span>');
  };

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
                onClick={() => setSelectedFile(tab.path)}
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
                {getIcon(tab.ext)}
                <span>{tab.name}</span>
                {tab.isAgentActive && <span className="agent-dot" style={{ width: '6px', height: '6px' }} />}
                <X size={12} style={{ opacity: 0.6, cursor: 'pointer' }} />
              </div>
            );
          })}
        </div>

        {/* Diff Mode Toggle Switch */}
        {(currentState === 'fix_proposed' || isDiffMode) && (
          <button 
            onClick={() => setIsDiffMode(!isDiffMode)}
            className="btn-outline"
            style={{ padding: '3px 8px', fontSize: '11px' }}
          >
            <Columns size={12} />
            <span>{isDiffMode ? 'Unified View' : 'Split View: Before / After'}</span>
          </button>
        )}
      </div>

      {/* Read-Only Banner when agent is diagnosing */}
      {currentState === 'diagnosing' && (
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
          <span>Read-only — API Doctor is actively analyzing this file</span>
        </div>
      )}

      {/* Code Editor Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {selectedFile === 'app/demo_api/bugs.py' ? (
          (currentState === 'fix_proposed' || isDiffMode) ? (
            /* SPLIT DIFF VIEW */
            <div style={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
              {/* Original Column */}
              <div style={{ flex: 1, borderRight: '1px solid var(--border-color)', overflowY: 'auto', padding: '8px 0' }}>
                <div style={{ padding: '4px 12px', fontSize: '11px', color: 'var(--color-failure)', fontWeight: 600, borderBottom: '1px solid var(--border-color)', marginBottom: '8px', fontFamily: 'var(--font-mono)' }}>
                  Original (bugs.py)
                </div>
                {bugsOriginalCode.map((row) => (
                  <div 
                    key={row.line}
                    style={{
                      display: 'flex',
                      lineHeight: '20px',
                      backgroundColor: row.isFailure ? 'var(--diff-remove-bg)' : 'transparent',
                      color: row.isFailure ? 'var(--diff-remove-text)' : 'var(--text-primary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ width: '45px', textAlign: 'right', paddingRight: '12px', color: 'var(--text-muted)', userSelect: 'none' }}>
                      {row.line}
                    </div>
                    <div style={{ paddingLeft: '8px', flex: 1, whiteSpace: 'pre' }}
                      dangerouslySetInnerHTML={{ __html: renderSyntaxHighlighted(row.code) }}
                    />
                  </div>
                ))}
              </div>

              {/* Proposed Column */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
                <div style={{ padding: '4px 12px', fontSize: '11px', color: 'var(--color-success)', fontWeight: 600, borderBottom: '1px solid var(--border-color)', marginBottom: '8px', fontFamily: 'var(--font-mono)' }}>
                  Proposed Fix (bugs.py)
                </div>
                {bugsProposedCode.map((row) => (
                  <div 
                    key={row.line}
                    style={{
                      display: 'flex',
                      lineHeight: '20px',
                      backgroundColor: row.type === 'add' ? 'var(--diff-add-bg)' : 'transparent',
                      color: row.type === 'add' ? 'var(--diff-add-text)' : 'var(--text-primary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ width: '45px', textAlign: 'right', paddingRight: '12px', color: 'var(--text-muted)', userSelect: 'none' }}>
                      {row.line}
                    </div>
                    <div style={{ paddingLeft: '8px', flex: 1, whiteSpace: 'pre' }}
                      dangerouslySetInnerHTML={{ __html: renderSyntaxHighlighted(row.code) }}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            /* STANDARD CODE VIEW WITH ANCHORED FAILURE CALLOUT */
            <div style={{ flex: 1, overflowY: 'auto', padding: '12px 0' }}>
              {bugsOriginalCode.map((row) => (
                <React.Fragment key={row.line}>
                  <div 
                    style={{
                      display: 'flex',
                      lineHeight: '22px',
                      backgroundColor: row.isFailure && (currentState === 'diagnosing' || currentState === 'idle') 
                        ? 'rgba(124, 140, 248, 0.15)' 
                        : 'transparent',
                      borderLeft: row.isFailure ? '3px solid var(--color-accent)' : '3px solid transparent',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ width: '50px', textAlign: 'right', paddingRight: '14px', color: 'var(--text-muted)', userSelect: 'none' }}>
                      {row.line}
                    </div>
                    <div style={{ flex: 1, paddingLeft: '8px', whiteSpace: 'pre' }}
                      dangerouslySetInnerHTML={{ __html: renderSyntaxHighlighted(row.code) }}
                    />
                  </div>

                  {/* Inline Anchored Failure Callout Card */}
                  {row.isFailure && (currentState === 'diagnosing' || currentState === 'idle') && (
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
                          <span>SUSPECTED FAILURE — LINE 122</span>
                        </div>
                        <X size={12} style={{ color: 'var(--text-muted)', cursor: 'pointer' }} />
                      </div>
                      <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '4px' }}>
                        AttributeError: 'NoneType' object has no attribute 'token'
                      </p>
                      <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        Line 122 attempts to dereference <code>payment_method</code> without checking if it is null when payload is empty.
                      </p>
                    </div>
                  )}
                </React.Fragment>
              ))}
            </div>
          )
        ) : (
          /* README FILE */
          <div style={{ flex: 1, padding: '24px', overflowY: 'auto', fontFamily: 'var(--font-ui)', color: 'var(--text-primary)' }}>
            <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', marginBottom: '12px', color: 'var(--color-accent)' }}>
              API Doctor: Auto-Diagnostic Toolkit
            </h1>
            <p style={{ color: 'var(--text-muted)', marginBottom: '16px', lineHeight: 1.6 }}>
              API Doctor is an autonomous debugging & repair agent operating directly inside your IDE environment.
            </p>
            <div style={{ backgroundColor: 'var(--surface-1)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>Key Capabilities</h3>
              <ul style={{ paddingLeft: '20px', color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.8 }}>
                <li>Live incident stack trace parsing</li>
                <li>Automated line-level root cause isolation</li>
                <li>Isolated sandbox test execution</li>
                <li>Pull Request generation with human approval gates</li>
              </ul>
            </div>
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
