import React, { useState } from 'react';
import { 
  Stethoscope, 
  ChevronRight, 
  ChevronDown, 
  CheckCircle2,
  XCircle,
  Clock,
  GitPullRequest,
  ExternalLink,
  ShieldCheck,
  Check, 
  ArrowUpRight,
  ChevronUp
} from 'lucide-react';

export default function APIDoctorPanel({ 
  incidentsList,
  activeIncident,
  incidentContext,
  incidentDiff,
  incidentSandbox,
  incidentPR,
  timelineEvents,
  isDiagnosing,
  onStartDiagnosis,
  onApproveFix,
  onCreatePR,
  onSelectIncident,
  doctorWidth, 
  isDoctorOpen, 
  setIsDoctorOpen,
  setSelectedFile,
  setIsDiffMode
}) {
  const [expandedFiles, setExpandedFiles] = useState(true);
  const [expandedFileDetails, setExpandedFileDetails] = useState({});
  const [historyOpen, setHistoryOpen] = useState(true);
  const rootCause = activeIncident?.root_cause;
  const confidence = Number.isFinite(Number(rootCause?.confidence))
    ? Math.min(1, Math.max(0, Number(rootCause.confidence)))
    : null;
  const confidencePercent = confidence === null ? null : Math.round(confidence * 100);

  if (!isDoctorOpen) return null;

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
          <span style={{ 
            width: '6px', 
            height: '6px', 
            borderRadius: '50%', 
            backgroundColor: isDiagnosing ? 'var(--color-accent)' : 'var(--color-success)' 
          }} />
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
        
        {/* IDLE STATE */}
        {!activeIncident && (
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
              No active incident selected. Trigger an automated run to test backend APIs.
            </p>
            <button 
              onClick={() => onStartDiagnosis('null_pointer')}
              className="btn-primary"
              style={{ width: '100%', justifyContent: 'center', padding: '8px 16px' }}
            >
              <Stethoscope size={14} />
              <span>Start Diagnosis (null_pointer)</span>
            </button>
          </div>
        )}

        {/* ACTIVE INCIDENT STATE */}
        {activeIncident && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            
            {/* Section 1: Current Incident Header */}
            <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                CURRENT INCIDENT
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-primary)', fontSize: '12px' }}>
                  #{activeIncident.id.slice(0, 8).toUpperCase()}
                </span>
                <span style={{ 
                  backgroundColor: activeIncident.status?.includes('VERIFIED') || activeIncident.status?.includes('PR') 
                    ? 'rgba(61, 214, 140, 0.15)' 
                    : 'rgba(240, 96, 90, 0.15)', 
                  color: activeIncident.status?.includes('VERIFIED') || activeIncident.status?.includes('PR')
                    ? 'var(--color-success)'
                    : 'var(--color-failure)', 
                  padding: '2px 8px', 
                  borderRadius: '4px', 
                  fontSize: '11px', 
                  fontWeight: 600, 
                  fontFamily: 'var(--font-mono)' 
                }}>
                  {activeIncident.status}
                </span>
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                <span>{activeIncident.detection?.method || 'POST'} {activeIncident.detection?.endpoint || '/api/v1/checkout'}</span>
                <span>{activeIncident.created_at ? new Date(activeIncident.created_at).toLocaleTimeString() : ''}</span>
              </div>
            </div>

            {/* Section 2: Live Investigation Timeline */}
            <div>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '10px' }}>
                LIVE INVESTIGATION TIMELINE
              </div>
              
              <div style={{ paddingLeft: '8px', position: 'relative' }}>
                <div style={{ position: 'absolute', left: '15px', top: '10px', bottom: '10px', width: '2px', backgroundColor: 'var(--border-color)', zIndex: 0 }} />

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', position: 'relative', zIndex: 1 }}>
                  {timelineEvents && timelineEvents.length > 0 ? (
                    timelineEvents.map((ev, index) => (
                      <div key={index} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                        {ev.status === 'running' ? (
                          <div style={{ width: '16px', height: '16px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-1)' }}>
                            <span className="agent-dot" />
                          </div>
                        ) : (
                          <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: `1px solid ${['failed', 'cancelled'].includes(ev.status) ? 'var(--color-failure)' : 'var(--color-success)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ['failed', 'cancelled'].includes(ev.status) ? 'var(--color-failure)' : 'var(--color-success)' }}>
                            {['failed', 'cancelled'].includes(ev.status) ? <XCircle size={10} /> : <Check size={10} />}
                          </div>
                        )}
                        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                          <span style={{ color: ev.status === 'running' ? 'var(--color-accent)' : 'var(--text-primary)', fontWeight: ev.status === 'running' ? 600 : 400 }}>
                            {ev.step || ev.message || 'Processing investigation step'}
                          </span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
                            {ev.timestamp || ev.ts ? new Date(ev.timestamp || ev.ts * 1000).toLocaleTimeString() : ''}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Initializing timeline stream...</div>
                  )}
                </div>
              </div>
            </div>

            {/* Section 3: Implicated Relevant Files */}
            {incidentContext && incidentContext.implicated_files && incidentContext.implicated_files.length > 0 && (
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
                  <span>{incidentContext.implicated_files.length} files analyzed</span>
                  {expandedFiles ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </div>

                {expandedFiles && (
                  <div style={{ padding: '6px 0', backgroundColor: 'var(--surface-1)' }}>
                    {incidentContext.implicated_files.map((filePath) => (
                      <div key={filePath} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <div 
                          onClick={() => { setSelectedFile(filePath); toggleFileDetail(filePath); }}
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
                            <span style={{ color: 'var(--text-primary)' }}>{filePath}</span>
                          </div>
                          <ChevronRight size={12} style={{ color: 'var(--text-muted)' }} />
                        </div>
                        
                        {expandedFileDetails[filePath] && (
                          <div style={{ padding: '6px 12px 6px 30px', fontSize: '11px', color: 'var(--text-muted)', backgroundColor: 'var(--bg-canvas)' }}>
                            Selected by AST & stack trace analyzer as implicated source.
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Section 4: Root Cause Card */}
            <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
                  ROOT CAUSE ANALYSIS
                </div>
                {rootCause?.category && (
                  <span style={{ backgroundColor: 'rgba(240, 96, 90, 0.15)', color: 'var(--color-failure)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 700 }}>
                    {rootCause.category.replaceAll('_', ' ')}
                  </span>
                )}
              </div>

              {!rootCause ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Clock size={13} />
                  <span>Agent analyzing stack trace & context...</span>
                </div>
              ) : (
                <>
                  {confidencePercent !== null && (
                    <div style={{ marginBottom: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Confidence</span>
                        <span style={{ color: 'var(--color-success)', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{confidencePercent}%</span>
                      </div>
                      <div style={{ height: '4px', backgroundColor: 'var(--border-color)', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ width: `${confidencePercent}%`, height: '100%', backgroundColor: 'var(--color-success)' }} />
                      </div>
                    </div>
                  )}

                  <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '6px', lineHeight: 1.4 }}>
                    {rootCause.root_cause || 'Root cause identified.'}
                  </p>
                  {rootCause.reason && (
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', lineHeight: 1.4 }}>
                      {rootCause.reason}
                    </p>
                  )}

                  {incidentContext?.implicated_files?.[0] && (
                    <button 
                      onClick={() => setSelectedFile(incidentContext.implicated_files[0])}
                      className="btn-outline"
                      style={{ width: '100%', justifyContent: 'center', fontSize: '11px' }}
                    >
                      <span>Open File ({incidentContext.implicated_files[0]})</span>
                      <ArrowUpRight size={12} />
                    </button>
                  )}
                </>
              )}
            </div>

            {/* Section 5: Proposed Fix Card */}
            {incidentDiff && incidentDiff.present && (
              <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                  AI PROPOSED CHANGE
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', fontFamily: 'var(--font-mono)' }}>
                  {incidentDiff.files_changed?.length || 1} file(s) changed
                </div>

                <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '12px' }}>
                  {incidentDiff.summary}
                </p>

                {/* Approvals */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <button onClick={() => onApproveFix(true)} className="btn-success" style={{ justifyContent: 'center', width: '100%' }}>
                    <Check size={14} />
                    <span>Keep Changes</span>
                  </button>

                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={() => onApproveFix(false)} className="btn-outline" style={{ flex: 1, justifyContent: 'center' }}>
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
              </div>
            )}

            {/* Section 6: Sandbox Result */}
            {incidentSandbox && incidentSandbox.present && (
              <div style={{ 
                backgroundColor: incidentSandbox.passed ? 'rgba(61, 214, 140, 0.08)' : 'rgba(240, 96, 90, 0.08)', 
                border: `1px solid ${incidentSandbox.passed ? 'var(--color-success)' : 'var(--color-failure)'}`, 
                borderRadius: '6px', 
                padding: '12px' 
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: incidentSandbox.passed ? 'var(--color-success)' : 'var(--color-failure)', fontWeight: 700, fontSize: '13px', marginBottom: '6px' }}>
                  <ShieldCheck size={18} />
                  <span>{incidentSandbox.passed ? 'FIX VERIFIED' : 'VERIFICATION FAILED'}</span>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '8px' }}>
                  {incidentSandbox.passed ? 'Original error resolved in verification sandbox.' : incidentSandbox.error || 'Tests failed.'}
                </p>
                {incidentSandbox.steps && (
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                    Steps completed: {incidentSandbox.steps.length}
                  </div>
                )}
              </div>
            )}

            {/* Section 7: GitHub PR Card */}
            {incidentPR && incidentPR.present && (
              <div style={{ backgroundColor: 'var(--surface-2)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                  GITHUB PULL REQUEST
                </div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                  PR #{incidentPR.pr_number || '1'} — API Repair
                </div>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Branch: <code>{incidentPR.branch || 'fix/api-doctor'}</code>
                </div>
                <div style={{ display: 'inline-block', backgroundColor: 'rgba(232, 162, 61, 0.15)', color: 'var(--color-warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, marginBottom: '12px' }}>
                  {incidentPR.status || 'Awaiting human review'}
                </div>

                <a 
                  href={incidentPR.pr_url || '#'} 
                  target="_blank" 
                  rel="noreferrer" 
                  className="btn-primary" 
                  style={{ width: '100%', justifyContent: 'center', textDecoration: 'none' }}
                >
                  <span>Open Pull Request</span>
                  <ExternalLink size={12} />
                </a>
              </div>
            )}

            {/* Create PR button if approved & sandbox passed */}
            {incidentSandbox && incidentSandbox.passed && (!incidentPR || !incidentPR.present) && (
              <button onClick={onCreatePR} className="btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                <GitPullRequest size={14} />
                <span>Create GitHub Pull Request</span>
              </button>
            )}

          </div>
        )}

        {/* Persistent Incident History */}
        <div style={{ marginTop: '24px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
          <div 
            onClick={() => setHistoryOpen(!historyOpen)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', marginBottom: '10px' }}
          >
            <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
              BACKEND INCIDENT HISTORY ({incidentsList ? incidentsList.length : 0})
            </span>
            {historyOpen ? <ChevronUp size={14} style={{ color: 'var(--text-muted)' }} /> : <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />}
          </div>

          {historyOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {incidentsList && incidentsList.length > 0 ? (
                incidentsList.map(inc => (
                  <div 
                    key={inc.id} 
                    onClick={() => onSelectIncident(inc.id)}
                    style={{
                      padding: '8px 10px',
                      backgroundColor: activeIncident?.id === inc.id ? 'var(--surface-hover)' : 'var(--surface-2)',
                      borderLeft: activeIncident?.id === inc.id ? '2px solid var(--color-accent)' : '2px solid transparent',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justify: 'space-between',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer'
                    }}
                  >
                    <span>#{inc.id.slice(0, 8).toUpperCase()}</span>
                    <span style={{ 
                      color: inc.status?.includes('VERIFIED') ? 'var(--color-success)' : 'var(--color-failure)', 
                      fontWeight: 600, 
                      fontSize: '10px' 
                    }}>
                      {inc.status}
                    </span>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>No backend incidents stored yet.</div>
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
