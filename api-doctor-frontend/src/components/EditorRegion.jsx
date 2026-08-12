import React from 'react';
import { 
  X, 
  Lock, 
  FileCode, 
  FileText, 
  FileLock, 
  Columns, 
  AlertTriangle 
} from 'lucide-react';

export default function EditorRegion({ 
  selectedFile, 
  setSelectedFile, 
  incidentContext,
  incidentDiff,
  isDiagnosing,
  isDiffMode,
  setIsDiffMode
}) {
  const openTabs = [
    { path: selectedFile || 'app/demo_api/bugs.py', name: selectedFile ? selectedFile.split('/').pop() : 'bugs.py', isAgentActive: isDiagnosing },
    { path: 'README.md', name: 'README.md' },
  ];

  const renderSyntaxHighlighted = (codeStr) => {
    if (!codeStr) return '';
    return codeStr
      .replace(/(def|return|if|not|raise|import|from|try|except)/g, '<span style="color:#7C8CF8;font-weight:500;">$1</span>')
      .replace(/(".*?"|'.*?')/g, '<span style="color:#3DD68C;">$1</span>')
      .replace(/(#.*)/g, '<span style="color:#8B8D93;font-style:italic;">$1</span>');
  };

  // Extract snippet or raw code from backend context
  const getCodeSnippet = () => {
    if (incidentContext && incidentContext.code_snippets) {
      const snip = incidentContext.code_snippets[selectedFile];
      if (typeof snip === 'string') return snip;
      if (snip && typeof snip === 'object') {
        if (typeof snip.code === 'string') return snip.code;
        if (Array.isArray(snip.lines)) return snip.lines.join('\n');
        return JSON.stringify(snip, null, 2);
      }
      // If code_snippets has keys, grab first snippet code if selectedFile not found directly
      const firstKey = Object.keys(incidentContext.code_snippets)[0];
      if (firstKey) {
        const firstSnip = incidentContext.code_snippets[firstKey];
        if (typeof firstSnip === 'string') return firstSnip;
        if (firstSnip && typeof firstSnip.code === 'string') return firstSnip.code;
      }
    }
    // Fallback real bug sample if file selected matches bugs.py
    return `def process_checkout(request_data):
    """Process API checkout order and validate payload"""
    user_id = request_data.get("user_id")
    order_amount = request_data.get("amount")
    payment_method = request_data.get("payment_method")

    # Issue: payment_method can be NoneType when missing from request
    payment_token = payment_method.token  # Line 122: UNSAFE ACCESS
    
    logger.info(f"Processing order for user {user_id} with token {payment_token}")
    return {"status": "success", "token": payment_token}`;
  };

  const rawCode = getCodeSnippet();
  const safeCodeStr = typeof rawCode === 'string' ? rawCode : String(rawCode || '');
  const lines = safeCodeStr.split('\n');

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
                <FileCode size={13} style={{ color: '#3572A5' }} />
                <span>{tab.name}</span>
                {tab.isAgentActive && <span className="agent-dot" style={{ width: '6px', height: '6px' }} />}
                <X size={12} style={{ opacity: 0.6, cursor: 'pointer' }} />
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
            {lines.map((lineText, idx) => {
              const lineNum = idx + 115;
              const isFailureLine = lineText.includes('payment_method.token') || lineText.includes('UNSAFE');
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
                    <div style={{ flex: 1, paddingLeft: '8px', whiteSpace: 'pre' }}
                      dangerouslySetInnerHTML={{ __html: renderSyntaxHighlighted(lineText) }}
                    />
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
