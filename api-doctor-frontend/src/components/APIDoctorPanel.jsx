import React, { useState } from 'react';
import { 
  Stethoscope, 
  ChevronRight, 
  ChevronDown, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  FileCode, 
  GitPullRequest, 
  ExternalLink, 
  RefreshCw, 
  AlertCircle, 
  ShieldCheck, 
  Check, 
  ArrowUpRight,
  ChevronUp
} from 'lucide-react';

export default function APIDoctorPanel({ 
  currentState, 
  setCurrentState, 
  doctorWidth, 
  isDoctorOpen, 
  setIsDoctorOpen,
  setSelectedFile,
  setIsDiffMode
}) {
  const [expandedFiles, setExpandedFiles] = useState(true);
  const [expandedFileDetails, setExpandedFileDetails] = useState({});
  const [historyOpen, setHistoryOpen] = useState(true);
  const [fixApplied, setFixApplied] = useState(false);

  if (!isDoctorOpen) return null;

  const handleKeepChanges = () => {
    setFixApplied(true);
    setCurrentState('verified_pr');
  };

  const handleReject = () => {
    setFixApplied(false);
    setCurrentState('idle');
  };

  const toggleFileDetail = (path) => {
    setExpandedFileDetails(prev => ({ ...prev, [path]: !prev[path] }));
  };

  return (
    <div style={{
      width: `${doctorWidth}px`,
      height: '100%',
      backgroundColor: 'var(--surface-1)',
      borderLeft: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      userSelect: 'none',
      zIndex: 30
    }}>
      {/* Panel Fixed Header */}
      <div style={{
        height: '35px',
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        justify: 'space-between',
        borderBottom: '1px solid var(--border-color)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Stethoscope size={15} style={{ color: 'var(--color-accent)' }} />
          <span style={{ 
            fontSize: '11px', 
            fontWeight: 700, 
            letterSpacing: '0.08em', 
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-heading)' 
          }}>
            API DOCTOR
          </span>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-success)' }} />
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button 
            onClick={() => setIsDoctorOpen(false)}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Panel Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
        
        {/* 7a. IDLE STATE */}
        {currentState === 'idle' && (
          <div style={{ textAlign: 'center', padding: '24px 12px' }}>
            <div style={{
              width: '48px',
              height: '48px',
              borderRadius: '50%',
              backgroundColor: 'var(--surface-2)',
              border: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justify: 'center',
              margin: '0 auto 16px auto',
              color: 'var(--color-accent)'
            }}>
              <Stethoscope size={24} />
            </div>
            <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '6px', color: 'var(--text-primary)' }}>
              Ready to diagnose your project.
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '20px' }}>
              No active incidents detected. Trigger an automated run or select a bug.
            </p>
            <button 
              onClick={() => setCurrentState('diagnosing')}
              className="btn-primary"
              style={{ width: '100%', justifyContent: 'center', padding: '8px 16px' }}
            >
              <Stethoscope size={14} />
              <span>Start Diagnosis</span>
            </button>
          </div>
        )}

        {/* 7b. ACTIVE / DIAGNOSING / FIX / VERIFIED STATES */}
        {currentState !== 'idle' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            
            {/* Section 1: Current Incident */}
            <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                CURRENT INCIDENT
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-primary)', fontSize: '13px' }}>#C0489BDA</span>
                <span style={{ backgroundColor: 'rgba(240, 96, 90, 0.15)', color: 'var(--color-failure)', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                  HTTP 500
                </span>
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                <span>POST /api/v1/checkout</span>
                <span>14:32:05</span>
              </div>
            </div>

            {/* Section 2: Live Investigation Timeline */}
            <div>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '10px' }}>
                LIVE INVESTIGATION TIMELINE
              </div>
              
              <div style={{ paddingLeft: '8px', position: 'relative' }}>
                {/* Vertical connecting line */}
                <div style={{ position: 'absolute', left: '15px', top: '10px', bottom: '10px', width: '2px', backgroundColor: 'var(--border-color)', zIndex: 0 }} />

                {/* Event Rows */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', position: 'relative', zIndex: 1 }}>
                  
                  {/* Step 1 */}
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                    <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: '1px solid var(--color-success)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-success)', background: 'var(--surface-1)' }}>
                      <Check size={10} />
                    </div>
                    <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span style={{ color: 'var(--text-primary)' }}>Parsed HTTP 500 stack trace</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>14:32:05</span>
                    </div>
                  </div>

                  {/* Step 2 */}
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                    <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: '1px solid var(--color-success)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-success)', background: 'var(--surface-1)' }}>
                      <Check size={10} />
                    </div>
                    <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span style={{ color: 'var(--text-primary)' }}>Isolated 4 relevant workspace files</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>14:32:07</span>
                    </div>
                  </div>

                  {/* Step 3 (Active running or finished) */}
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                    {currentState === 'diagnosing' ? (
                      <div style={{ width: '16px', height: '16px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-1)' }}>
                        <span className="agent-dot" />
                      </div>
                    ) : (
                      <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: '1px solid var(--color-success)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-success)', background: 'var(--surface-1)' }}>
                        <Check size={10} />
                      </div>
                    )}
                    <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span style={{ color: currentState === 'diagnosing' ? 'var(--color-accent)' : 'var(--text-primary)', fontWeight: currentState === 'diagnosing' ? 600 : 400 }}>
                        {currentState === 'diagnosing' ? 'Analyzing app/demo_api/bugs.py...' : 'Identified AttributeError on line 122'}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>14:32:10</span>
                    </div>
                  </div>

                  {/* Step 4 */}
                  {currentState !== 'diagnosing' && (
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                      <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: '1px solid var(--color-success)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-success)', background: 'var(--surface-1)' }}>
                        <Check size={10} />
                      </div>
                      <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                        <span style={{ color: 'var(--text-primary)' }}>Generated proposed patch</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>14:32:14</span>
                      </div>
                    </div>
                  )}

                </div>
              </div>
            </div>

            {/* Section 3: Relevant Files */}
            <div style={{ border: '1px solid var(--border-color)', borderRadius: '6px', overflow: 'hidden' }}>
              <div 
                onClick={() => setExpandedFiles(!expandedFiles)}
                style={{
                  padding: '8px 12px',
                  backgroundColor: 'var(--surface-2)',
                  display: 'flex',
                  alignItems: 'center',
                  justify: 'space-between',
                  cursor: 'pointer',
                  fontSize: '11px',
                  fontWeight: 600
                }}
              >
                <span>4 files analyzed</span>
                {expandedFiles ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </div>

              {expandedFiles && (
                <div style={{ padding: '6px 0', backgroundColor: 'var(--surface-1)' }}>
                  {[
                    { path: 'app/demo_api/bugs.py', reason: 'Direct stack trace failure origin' },
                    { path: 'app/demo_api/checkout.py', reason: 'Invokes payment handler' },
                    { path: 'app/routes/payments.py', reason: 'Endpoint router specification' },
                    { path: 'requirements.txt', reason: 'Dependency version checks' }
                  ].map((f) => (
                    <div key={f.path} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <div 
                        onClick={() => { setSelectedFile(f.path); toggleFileDetail(f.path); }}
                        style={{
                          padding: '6px 12px',
                          display: 'flex',
                          alignItems: 'center',
                          justify: 'space-between',
                          cursor: 'pointer',
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)'
                        }}
                        className="hover-bg"
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <CheckCircle2 size={12} style={{ color: 'var(--color-success)' }} />
                          <span style={{ color: 'var(--text-primary)' }}>{f.path}</span>
                        </div>
                        <ChevronRight size={12} style={{ color: 'var(--text-muted)' }} />
                      </div>
                      
                      {expandedFileDetails[f.path] && (
                        <div style={{ padding: '6px 12px 6px 30px', fontSize: '11px', color: 'var(--text-muted)', backgroundColor: 'var(--bg-canvas)' }}>
                          Why this file? {f.reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Section 4: Root Cause */}
            <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
                  ROOT CAUSE
                </div>
                {currentState !== 'diagnosing' && (
                  <span style={{ backgroundColor: 'rgba(240, 96, 90, 0.15)', color: 'var(--color-failure)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 700 }}>
                    CODE BUG
                  </span>
                )}
              </div>

              {currentState === 'diagnosing' ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Clock size={13} />
                  <span>Waiting for investigation...</span>
                </div>
              ) : (
                <>
                  {/* Confidence Bar */}
                  <div style={{ marginBottom: '10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Confidence</span>
                      <span style={{ color: 'var(--color-success)', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>96%</span>
                    </div>
                    <div style={{ height: '4px', backgroundColor: 'var(--border-color)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div style={{ width: '96%', height: '100%', backgroundColor: 'var(--color-success)' }} />
                    </div>
                  </div>

                  <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '10px', lineHeight: 1.4 }}>
                    <code>payment_method</code> evaluates to <code>None</code> when <code>payment_method</code> payload field is omitted, causing <code>AttributeError</code> on dereference.
                  </p>

                  <button 
                    onClick={() => setSelectedFile('app/demo_api/bugs.py')}
                    className="btn-outline"
                    style={{ width: '100%', justifyContent: 'center', fontSize: '11px' }}
                  >
                    <span>Open Location (bugs.py:121)</span>
                    <ArrowUpRight size={12} />
                  </button>
                </>
              )}
            </div>

            {/* Section 5: Proposed Fix / Change Approval */}
            {currentState !== 'diagnosing' && (
              <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                  AI PROPOSED CHANGE
                </div>

                {!fixApplied && currentState === 'fix_proposed' ? (
                  <>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', fontFamily: 'var(--font-mono)' }}>
                      1 file changed · <span style={{ color: 'var(--color-success)' }}>+3</span> <span style={{ color: 'var(--color-failure)' }}>−1</span>
                    </div>
                    <ul style={{ paddingLeft: '16px', fontSize: '11px', color: 'var(--text-primary)', marginBottom: '14px', lineHeight: 1.6 }}>
                      <li><span style={{ color: 'var(--color-success)' }}>+</span> Added null safety check for payment_method</li>
                      <li><span style={{ color: 'var(--color-failure)' }}>−</span> Removed unsafe direct property dereference</li>
                    </ul>

                    {/* Semantically distinct buttons */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <button onClick={handleKeepChanges} className="btn-success" style={{ justifyContent: 'center', width: '100%' }}>
                        <Check size={14} />
                        <span>Keep Changes</span>
                      </button>

                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button onClick={handleReject} className="btn-outline" style={{ flex: 1, justifyContent: 'center' }}>
                          Reject
                        </button>
                        <button 
                          onClick={() => setIsDiffMode(true)} 
                          style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: '11px', textDecoration: 'underline' }}
                        >
                          Review Full Diff
                        </button>
                      </div>
                    </div>
                  </>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-success)', fontSize: '12px', fontWeight: 500 }}>
                    <CheckCircle2 size={16} />
                    <span>Changes applied to workspace</span>
                  </div>
                )}
              </div>
            )}

            {/* Section 6: Sandbox & GitHub PR (Visible when verified) */}
            {currentState === 'verified_pr' && (
              <>
                {/* Verification Box */}
                <div style={{ backgroundColor: 'rgba(61, 214, 140, 0.08)', border: '1px solid var(--color-success)', borderRadius: '6px', padding: '12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-success)', fontWeight: 700, fontSize: '13px', marginBottom: '6px' }}>
                    <ShieldCheck size={18} />
                    <span>FIX VERIFIED</span>
                  </div>
                  <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '8px' }}>
                    Original HTTP 500 error no longer reproduced in sandbox.
                  </p>
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                    Test stats: <span style={{ color: 'var(--color-success)' }}>12 passed</span> · 0 failed
                  </div>
                </div>

                {/* GitHub PR Card */}
                <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                    GITHUB PULL REQUEST
                  </div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                    Fix payment method null handling
                  </div>
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: '8px' }}>
                    Branch: <code>api-doctor/fix/c0489bda</code>
                  </div>
                  <div style={{ display: 'inline-block', backgroundColor: 'rgba(232, 162, 61, 0.15)', color: 'var(--color-warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, marginBottom: '12px' }}>
                    Awaiting human review
                  </div>

                  <button className="btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                    <span>Open Pull Request</span>
                    <ExternalLink size={12} />
                  </button>
                  <div style={{ textAlign: 'center', fontSize: '10px', color: 'var(--text-muted)', marginTop: '6px' }}>
                    Note: Merging requires human PR review on GitHub.
                  </div>
                </div>
              </>
            )}

          </div>
        )}

        {/* Persistent Incident History (§12) */}
        <div style={{ marginTop: '24px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
          <div 
            onClick={() => setHistoryOpen(!historyOpen)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', marginBottom: '10px' }}
          >
            <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
              INCIDENT HISTORY
            </span>
            {historyOpen ? <ChevronUp size={14} style={{ color: 'var(--text-muted)' }} /> : <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />}
          </div>

          {historyOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[
                { id: '#C0489BDA', status: 'FIX VERIFIED', color: 'var(--color-success)' },
                { id: '#A12F94BC', status: 'PR OPEN', color: 'var(--color-warning)' },
                { id: '#79B8823D', status: 'FIX FAILED', color: 'var(--color-failure)' }
              ].map(inc => (
                <div key={inc.id} style={{
                  padding: '8px 10px',
                  backgroundColor: 'var(--surface-2)',
                  borderRadius: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justify: 'space-between',
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)'
                }}>
                  <span>{inc.id}</span>
                  <span style={{ color: inc.color, fontWeight: 600, fontSize: '10px' }}>{inc.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
