import React, { useMemo, useState } from 'react';
import {
  Stethoscope,
  ChevronRight,
  ChevronDown,
  XCircle,
  Clock,
  GitPullRequest,
  GitCommit,
  ExternalLink,
  ShieldCheck,
  Check,
  ArrowUpRight,
  ChevronUp,
  Server,
  FileText,
  History
} from 'lucide-react';

const STEP_LABELS = {
  pipeline: 'Diagnosis pipeline',
  repository_check: 'Verifying repository workspace',
  repository_connected: 'Repository connected',
  github_connected: 'Repository connected',
  repository_verified: 'Repository verified',
  repository_synced: 'Workspace state checked',
  repository_synchronized: 'Project synchronized',
  project_discovered: 'Project discovered',
  logs_retrieved: 'Logs retrieved',
  error_detected: 'Error detected',
  stack_trace_parsed: 'Stack trace parsed',
  relevant_source_identified: 'Relevant files identified',
  files_to_read: 'Files identified for reading',
  file_read: 'Reading source file',
  file_read_approval: 'File read approval',
  collecting_context: 'Building investigation context',
  investigating: 'Investigating root cause',
  investigation_started: 'Investigating root cause',
  root_cause_identified: 'Root cause identified',
  fix_generated: 'Generating fix',
  fix_approval: 'Fix approval',
  diff_ready: 'Proposed diff ready',
  changes_applied: 'Applying changes to workspace',
  changes_rolled_back: 'Workspace rollback',
  workspace_updated: 'Workspace updated',
  sandbox_started: 'Sandbox verification',
  tests_started: 'Running tests',
  test_passed: 'Tests passed',
  fix_verified: 'Fix verified',
  local_commit: 'Local commit',
  branch_created: 'Repair branch created',
  commit_created: 'Commit created',
  pr_created: 'Pull request created',
  fix_rejected: 'Patch rejected'
};

// Steps that repeat with a different target per event (one row per file).
const REPEATING_STEPS = new Set(['file_read']);

function normalizeFileReadMessage(message = '') {
  return message.replace(/^(Reading|Read)\s+/, '').split(' · ')[0].trim();
}

/**
 * Merge raw SSE events into timeline rows. A "running" event and its later
 * "done"/"failed" event share the same key and collapse into one row, so the
 * UI shows live progress instead of a prewritten checklist.
 */
export function buildTimeline(events = []) {
  const rows = [];
  const indexByKey = new Map();

  for (const ev of events) {
    if (!ev || ev.type === 'connected') continue;
    const step = ev.step || '';
    const message = ev.message || '';
    if (!step && !message) continue;

    let key = step || `msg:${message}`;
    if (REPEATING_STEPS.has(step)) key = `${step}::${normalizeFileReadMessage(message)}`;

    const time = ev.ts
      ? new Date(ev.ts * 1000)
      : ev.timestamp
        ? new Date(ev.timestamp)
        : null;

    const existingIndex = indexByKey.get(key);
    if (existingIndex !== undefined) {
      const row = rows[existingIndex];
      row.status = ev.status || row.status;
      if (message) row.message = message;
      if (time) row.time = time;
    } else {
      indexByKey.set(key, rows.length);
      rows.push({
        key,
        step,
        status: ev.status || 'running',
        label: STEP_LABELS[step] || (step ? step.replace(/_/g, ' ') : message),
        message,
        time,
        replay: Boolean(ev.replay)
      });
    }
  }
  return rows;
}

function TimelineRow({ row }) {
  const isRunning = row.status === 'running';
  const isPending = row.status === 'pending' || row.status === 'paused';
  const isFailed = row.status === 'failed' || row.status === 'cancelled';
  const detail = row.message && row.message !== row.label ? row.message : '';

  return (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
      {isRunning ? (
        <div style={{ width: '16px', height: '16px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-1)', flexShrink: 0 }}>
          <span className="agent-dot" />
        </div>
      ) : isPending ? (
        <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: '1px solid var(--color-warning)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-warning)', flexShrink: 0 }}>
          <Clock size={10} />
        </div>
      ) : (
        <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: 'var(--surface-1)', border: `1px solid ${isFailed ? 'var(--color-failure)' : 'var(--color-success)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: isFailed ? 'var(--color-failure)' : 'var(--color-success)', flexShrink: 0 }}>
          {isFailed ? <XCircle size={10} /> : <Check size={10} />}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', gap: '8px' }}>
          <span style={{
            color: isRunning || isPending ? 'var(--color-accent)' : 'var(--text-primary)',
            fontWeight: isRunning ? 600 : 400
          }}>
            {row.label}{isRunning && !detail ? '…' : ''}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>
            {row.time ? row.time.toLocaleTimeString() : ''}
          </span>
        </div>
        {detail && (
          <div style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            color: isFailed ? 'var(--color-failure)' : 'var(--text-muted)',
            marginTop: '1px',
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap'
          }}>
            {detail}
          </div>
        )}
      </div>
    </div>
  );
}

export default function APIDoctorPanel({
  incidentsList = [],
  activeIncident,
  incidentContext,
  incidentDiff,
  incidentSandbox,
  incidentPR,
  timelineEvents = [],
  isDiagnosing,
  isIncidentActionPending = false,
  onKeepChanges,
  onRejectChanges,
  onApplyFix,
  onCommitChanges,
  onCreatePR,
  onApproveFileRead,
  onSelectIncident,
  onSyncRender,
  onOpenIngestModal,
  doctorWidth = 380,
  isDoctorOpen = true,
  setIsDoctorOpen,
  setSelectedFile,
  setIsDiffMode
}) {
  const [expandedFiles, setExpandedFiles] = useState(true);
  // History is secondary — collapsed by default so the active diagnosis owns
  // the panel.
  const [historyOpen, setHistoryOpen] = useState(false);

  const timelineRows = useMemo(() => buildTimeline(timelineEvents), [timelineEvents]);

  const rootCause = activeIncident?.root_cause;
  const confidence = Number.isFinite(Number(rootCause?.confidence))
    ? Math.min(1, Math.max(0, Number(rootCause.confidence)))
    : null;
  const confidencePercent = confidence === null ? null : Math.round(confidence * 100);

  if (!isDoctorOpen) return null;

  const getClassification = () => {
    if (!rootCause) return null;
    return rootCause.classification || rootCause.category || 'CODE_BUG';
  };

  const appliedFiles = activeIncident?.applied_files || [];
  const isAwaitingFix = activeIncident?.status === 'AWAITING_FIX_APPROVAL';
  const isVerified = Boolean(incidentSandbox?.passed);
  const wasRolledBack = timelineRows.some(r => r.step === 'changes_rolled_back');

  const historyItems = (incidentsList || []).filter(inc => inc.id !== activeIncident?.id);

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
        justifyContent: 'space-between',
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
              justifyContent: 'center',
              margin: '0 auto 16px auto',
              color: 'var(--color-accent)'
            }}>
              <Stethoscope size={24} />
            </div>
            <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '6px', color: 'var(--text-primary)' }}>
              Ready to diagnose your project.
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '20px', lineHeight: 1.5 }}>
              Retrieve real Render logs automatically, or paste production errors manually when the logs come from another source.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                onClick={onSyncRender}
                className="btn-primary"
                style={{ width: '100%', justifyContent: 'center', padding: '8px 16px' }}
              >
                <Server size={14} />
                <span>Sync Render Runtime Logs</span>
              </button>
              <button
                onClick={onOpenIngestModal}
                className="btn-outline"
                style={{ width: '100%', justifyContent: 'center', padding: '8px 16px' }}
              >
                <FileText size={14} />
                <span>Ingest Production Log / Error</span>
              </button>
            </div>
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
                    ? 'rgba(16, 185, 129, 0.15)'
                    : activeIncident.status?.includes('FAIL')
                      ? 'rgba(244, 63, 94, 0.15)'
                      : 'rgba(240, 169, 58, 0.15)',
                  color: activeIncident.status?.includes('VERIFIED') || activeIncident.status?.includes('PR')
                    ? 'var(--color-success)'
                    : activeIncident.status?.includes('FAIL')
                      ? 'var(--color-failure)'
                      : 'var(--color-accent)',
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
                <span>{activeIncident.detection?.source ? `Source: ${activeIncident.detection.source}` : (activeIncident.detection?.endpoint || 'Error Ingested')}</span>
                <span>{activeIncident.created_at ? new Date(activeIncident.created_at).toLocaleTimeString() : ''}</span>
              </div>
              {(activeIncident.error_message || activeIncident.detection?.error_message) && (
                <div style={{
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-failure)',
                  backgroundColor: 'rgba(244, 63, 94, 0.08)',
                  border: '1px solid rgba(244, 63, 94, 0.25)',
                  borderRadius: '4px',
                  padding: '6px 8px',
                  marginTop: '8px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  lineHeight: 1.4
                }}>
                  {activeIncident.error_message || activeIncident.detection?.error_message}
                </div>
              )}
            </div>

            {/* Section 2: Live Investigation Timeline — driven only by real backend events */}
            <div>
              <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '10px' }}>
                LIVE INVESTIGATION
              </div>

              <div style={{ paddingLeft: '8px', position: 'relative' }}>
                {timelineRows.length > 0 && (
                  <div style={{ position: 'absolute', left: '15px', top: '10px', bottom: '10px', width: '2px', backgroundColor: 'var(--border-color)', zIndex: 0 }} />
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', position: 'relative', zIndex: 1 }}>
                  {timelineRows.length > 0 ? (
                    timelineRows.map(row => <TimelineRow key={row.key} row={row} />)
                  ) : isDiagnosing ? (
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center', fontSize: '12px', color: 'var(--color-accent)' }}>
                      <span className="agent-dot" />
                      <span>Starting diagnosis…</span>
                    </div>
                  ) : (
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      No investigation activity yet. Start a diagnosis to stream live agent events.
                    </div>
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
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    fontSize: '11px',
                    fontWeight: 600
                  }}
                >
                  <span>{incidentContext.implicated_files.length} relevant file(s) identified</span>
                  {expandedFiles ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </div>

                {expandedFiles && (
                  <div style={{ padding: '6px 0', backgroundColor: 'var(--surface-1)' }}>
                    {incidentContext.implicated_files.map((filePath) => (
                      <div key={filePath} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <div
                          onClick={() => setSelectedFile(filePath)}
                          style={{
                            padding: '6px 12px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            cursor: 'pointer',
                            fontSize: '11px',
                            fontFamily: 'var(--font-mono)'
                          }}
                          className="hover-bg"
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <Check size={12} style={{ color: 'var(--color-success)' }} />
                            <span style={{ color: 'var(--text-primary)' }}>{filePath}</span>
                          </div>
                          <ChevronRight size={12} style={{ color: 'var(--text-muted)' }} />
                        </div>
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
                {getClassification() && (
                  <span style={{ backgroundColor: 'rgba(244, 63, 94, 0.15)', color: 'var(--color-failure)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 700 }}>
                    {getClassification().replace(/_/g, ' ')}
                  </span>
                )}
              </div>

              {!rootCause ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Clock size={13} />
                  <span>{isDiagnosing ? 'Waiting for investigation results…' : 'No root cause analysis yet.'}</span>
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
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', lineHeight: 1.4 }}>
                      {rootCause.reason}
                    </p>
                  )}
                  {rootCause.recommended_action && (
                    <div style={{ fontSize: '11px', color: 'var(--color-accent)', marginBottom: '10px', backgroundColor: 'rgba(240, 169, 58, 0.08)', padding: '6px 8px', borderRadius: '4px' }}>
                      <strong>Action:</strong> {rootCause.recommended_action}
                    </div>
                  )}

                  {rootCause.affected_files?.[0] && (
                    <button
                      onClick={() => setSelectedFile(rootCause.affected_files[0])}
                      className="btn-outline"
                      style={{ width: '100%', justifyContent: 'center', fontSize: '11px' }}
                    >
                      <span>Open {rootCause.affected_files[0]}</span>
                      <ArrowUpRight size={12} />
                    </button>
                  )}
                </>
              )}
            </div>

            {/* Section 4b: File Read Approval (interactive workflow) */}
            {activeIncident?.status === 'AWAITING_FILE_READ_APPROVAL' && (
              <div style={{ backgroundColor: 'rgba(240, 169, 58, 0.08)', border: '1px solid rgba(240, 169, 58, 0.3)', borderRadius: '6px', padding: '12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--color-accent)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                  FILES TO READ — APPROVAL REQUIRED
                </div>
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', lineHeight: 1.4 }}>
                  The agent identified these files and wants to read them. Nothing is read until you approve.
                </p>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', backgroundColor: 'var(--surface-1)', padding: '8px', borderRadius: '4px', marginBottom: '12px', maxHeight: '120px', overflowY: 'auto' }}>
                  {(incidentContext?.implicated_files?.length
                    ? incidentContext.implicated_files
                    : activeIncident.context?.affected_files || []
                  ).map((filePath) => (
                    <div key={filePath} style={{ padding: '2px 0', color: 'var(--text-primary)' }}>
                      <ChevronRight size={10} style={{ marginRight: '4px', verticalAlign: 'middle' }} />
                      {filePath}
                    </div>
                  )) || <div style={{ color: 'var(--text-muted)' }}>No files identified</div>}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button disabled={isIncidentActionPending} onClick={() => onApproveFileRead(true)} className="btn-success" style={{ flex: 1, justifyContent: 'center' }}>
                    <Check size={14} />
                    <span>{isIncidentActionPending ? 'Recording…' : 'Approve Reading'}</span>
                  </button>
                  <button disabled={isIncidentActionPending} onClick={() => onApproveFileRead(false)} className="btn-outline" style={{ flex: 1, justifyContent: 'center' }}>
                    Deny
                  </button>
                </div>
              </div>
            )}

            {/* Section 5: Proposed Fix — Keep Changes / Reject / Review Diff */}
            {incidentDiff && incidentDiff.present && (
              <div style={{
                backgroundColor: isAwaitingFix ? 'rgba(240, 169, 58, 0.08)' : 'var(--surface-2)',
                border: `1px solid ${isAwaitingFix ? 'rgba(240, 169, 58, 0.3)' : 'var(--border-color)'}`,
                borderRadius: '6px',
                padding: '12px'
              }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: isAwaitingFix ? 'var(--color-accent)' : 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '8px' }}>
                  {isAwaitingFix ? 'AI PROPOSED PATCH — REVIEW REQUIRED' : 'AI PROPOSED PATCH'}
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', fontFamily: 'var(--font-mono)' }}>
                  {incidentDiff.files_changed?.length || 1} file(s) changed
                </div>

                <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '12px' }}>
                  {incidentDiff.summary}
                </p>

                {appliedFiles.length > 0 ? (
                  /* Already applied to the workspace */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      color: 'var(--color-success)', fontSize: '12px', fontWeight: 600
                    }}>
                      <Check size={14} />
                      <span>Changes applied to workspace</span>
                    </div>
                    <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      {appliedFiles.map(f => <div key={f}>• {f}</div>)}
                    </div>

                    {isVerified && !activeIncident.commit_sha && (
                      <button onClick={onCommitChanges} className="btn-primary" style={{ justifyContent: 'center', width: '100%' }}>
                        <GitCommit size={14} />
                        <span>Commit Changes</span>
                      </button>
                    )}
                    {activeIncident.commit_sha && (
                      <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--color-success)' }}>
                        ✓ Committed {String(activeIncident.commit_sha).slice(0, 12)}
                      </div>
                    )}
                    {isVerified && !(incidentPR && incidentPR.present) && (
                      <button onClick={onCreatePR} className="btn-outline" style={{ justifyContent: 'center', width: '100%' }}>
                        <GitPullRequest size={14} />
                        <span>Create Pull Request</span>
                      </button>
                    )}
                    <button
                      onClick={() => setIsDiffMode(true)}
                      style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: '11px', textDecoration: 'underline' }}
                    >
                      Review Diff
                    </button>
                  </div>
                ) : isAwaitingFix ? (
                  /* Awaiting user decision */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <button disabled={isIncidentActionPending} onClick={() => onKeepChanges(true)} className="btn-success" style={{ justifyContent: 'center', width: '100%' }}>
                      <Check size={14} />
                      <span>{isIncidentActionPending ? 'Applying…' : 'Keep Changes'}</span>
                    </button>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                      Applies the patch to your workspace, then verifies it in an isolated sandbox copy. If verification fails, the workspace is restored automatically.
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button onClick={() => onRejectChanges()} className="btn-outline" style={{ flex: 1, justifyContent: 'center' }}>
                        Reject
                      </button>
                      <button
                        onClick={() => setIsDiffMode(true)}
                        style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: '11px', textDecoration: 'underline' }}
                      >
                        Review Diff
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Proposal exists but was not applied (legacy / failed path) */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {onApplyFix && (
                      <button onClick={() => onApplyFix()} className="btn-success" style={{ justifyContent: 'center', width: '100%' }}>
                        <Check size={14} />
                        <span>Apply to Workspace</span>
                      </button>
                    )}
                    <button
                      onClick={() => setIsDiffMode(true)}
                      style={{ background: 'none', border: 'none', color: 'var(--color-accent)', cursor: 'pointer', fontSize: '11px', textDecoration: 'underline' }}
                    >
                      Review Diff
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Rollback notice */}
            {wasRolledBack && (
              <div style={{
                backgroundColor: 'rgba(244, 63, 94, 0.08)',
                border: '1px solid rgba(244, 63, 94, 0.3)',
                borderRadius: '6px',
                padding: '10px 12px',
                fontSize: '11px',
                color: 'var(--color-failure)',
                lineHeight: 1.5
              }}>
                Verification failed — your workspace was restored to the original code. Re-run the diagnosis to generate a fresh patch.
              </div>
            )}

            {/* Section 6: Sandbox Result */}
            {incidentSandbox && incidentSandbox.present && (
              <div style={{
                backgroundColor: incidentSandbox.passed ? 'rgba(16, 185, 129, 0.08)' : 'rgba(244, 63, 94, 0.08)',
                border: `1px solid ${incidentSandbox.passed ? 'var(--color-success)' : 'var(--color-failure)'}`,
                borderRadius: '6px',
                padding: '12px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: incidentSandbox.passed ? 'var(--color-success)' : 'var(--color-failure)', fontWeight: 700, fontSize: '13px', marginBottom: '6px' }}>
                  <ShieldCheck size={18} />
                  <span>{incidentSandbox.passed ? 'FIX VERIFIED' : 'VERIFICATION FAILED'}</span>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '8px' }}>
                  {incidentSandbox.passed
                    ? (appliedFiles.length ? 'Patch verified in an isolated sandbox copy and kept in your workspace.' : 'Patch verified in an isolated sandbox copy.')
                    : incidentSandbox.error || 'Verification tests failed.'}
                </p>
                {Array.isArray(incidentSandbox.steps) && incidentSandbox.steps.length > 0 && (
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    {incidentSandbox.steps.map(step => (
                      <div key={step.name} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {step.passed
                          ? <Check size={11} style={{ color: 'var(--color-success)' }} />
                          : <XCircle size={11} style={{ color: 'var(--color-failure)' }} />}
                        <span>{String(step.name).replace(/_/g, ' ')}</span>
                      </div>
                    ))}
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
                  PR #{incidentPR.pr_number || '1'} — API Doctor Repair
                </div>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Branch: <code>{incidentPR.branch || `api-doctor/fix/${activeIncident.id}`}</code>
                </div>
                <div style={{ display: 'inline-block', backgroundColor: 'rgba(245, 158, 11, 0.15)', color: 'var(--color-warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, marginBottom: '12px' }}>
                  {incidentPR.status || 'Ready for review'}
                </div>

                <a
                  href={incidentPR.pr_url || '#'}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-primary"
                  style={{ width: '100%', justifyContent: 'center', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <span>Open Pull Request</span>
                  <ExternalLink size={12} />
                </a>
              </div>
            )}

          </div>
        )}

        {/* Incident History — secondary, collapsed by default */}
        <div style={{ marginTop: '24px', borderTop: '1px solid var(--border-color)', paddingTop: '12px' }}>
          <div
            onClick={() => setHistoryOpen(!historyOpen)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', marginBottom: historyOpen ? '10px' : '0' }}
          >
            <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <History size={11} />
              INCIDENT HISTORY ({incidentsList ? incidentsList.length : 0})
            </span>
            {historyOpen ? <ChevronUp size={14} style={{ color: 'var(--text-muted)' }} /> : <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} />}
          </div>

          {historyOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {historyItems.length > 0 ? (
                historyItems.map(inc => (
                  <div
                    key={inc.id}
                    onClick={() => onSelectIncident(inc.id)}
                    style={{
                      padding: '8px 10px',
                      backgroundColor: 'var(--surface-2)',
                      borderLeft: '2px solid transparent',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer'
                    }}
                  >
                    <span>#{inc.id.slice(0, 8).toUpperCase()}</span>
                    <span style={{
                      color: inc.status?.includes('VERIFIED') || inc.status?.includes('PR')
                        ? 'var(--color-success)'
                        : inc.status?.includes('FAIL') || inc.status?.includes('CANCEL')
                          ? 'var(--color-failure)'
                          : 'var(--color-accent)',
                      fontWeight: 600,
                      fontSize: '10px'
                    }}>
                      {inc.status}
                    </span>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>No previous incidents.</div>
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
