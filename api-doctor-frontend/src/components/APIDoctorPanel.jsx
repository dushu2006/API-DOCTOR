import React, { useEffect, useRef, useState } from 'react';
import {
  Check,
  CheckCircle2,
  ChevronRight,
  FileCode2,
  GitCommit,
  GitPullRequest,
  Loader2,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react';
import { normalizedTarget, runningCopy } from '../diagnosisTimeline';

/* ---------------------------------------------------------------------------
 * Small presentation helpers
 * ------------------------------------------------------------------------- */

function lastMessage(stage) {
  const row = [...(stage.rows || [])].reverse().find((r) => r.message);
  return row?.message || '';
}

function truncate(text, max = 90) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function displayState(stage) {
  if (stage.phase === 'buffering') return 'running';
  return stage.status;
}

function displayMessage(stage, run, runDiff, runSandbox) {
  if (stage.phase === 'buffering') {
    // While genuinely in flight, prefer the backend's own live message.
    const live = [...(stage.rows || [])].reverse().find(
      (r) => r.status === 'running' && r.message
    );
    return live?.message || stage.displayMessage || runningCopy(stage.id);
  }
  if (stage.status === 'waiting') return 'Waiting for approval…';
  if (stage.status === 'failed') {
    const failedRow = (stage.rows || []).find(
      (r) => r.status === 'failed' || r.status === 'cancelled'
    );
    return failedRow?.message || 'Failed';
  }

  switch (stage.id) {
    case 'error':
      return lastMessage(stage).replace(/\s+on\s+/i, ' · ');
    case 'cause': {
      const rc = run?.root_cause;
      if (rc) {
        const pct = Math.round((rc.confidence ?? 0) * 100);
        return `${rc.classification || rc.category || 'CODE_BUG'} · ${pct}% confidence`;
      }
      break;
    }
    case 'fix':
    case 'review':
      if (runDiff?.summary) return runDiff.summary;
      break;
    case 'read': {
      const reads = (stage.rows || []).filter((r) => r.status === 'done');
      if (reads.length > 1) return `${reads.length} source files read`;
      break;
    }
    case 'verify':
      if (runSandbox?.present && runSandbox.passed) return 'Repair verified in sandbox';
      break;
    default:
      break;
  }
  return lastMessage(stage);
}

function StepIcon({ state }) {
  if (state === 'running') {
    return (
      <span className="dp-step-icon is-running">
        <Loader2 size={11} className="spin" />
      </span>
    );
  }
  if (state === 'done') {
    return (
      <span className="dp-step-icon is-done">
        <Check size={11} strokeWidth={3} />
      </span>
    );
  }
  if (state === 'waiting') {
    return (
      <span className="dp-step-icon is-waiting">
        <span className="dp-wait-dot" />
      </span>
    );
  }
  if (state === 'failed') {
    return (
      <span className="dp-step-icon is-failed">
        <X size={11} strokeWidth={3} />
      </span>
    );
  }
  return <span className="dp-step-icon" />;
}

function Row({ k, v, mono = false }) {
  if (v === undefined || v === null || v === '') return null;
  return (
    <div className="dp-row">
      <span className="dp-row-k">{k}</span>
      <span className={`dp-row-v${mono ? ' is-mono' : ''}`}>{v}</span>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Expanded step explanations (driven by real backend results)
 * ------------------------------------------------------------------------- */

function RootCauseCard({ rc }) {
  const pct = Math.round((rc?.confidence ?? 0) * 100);
  const location = (rc?.affected_files || [])
    .map((f, i) => `${f}${rc.affected_lines?.[i] != null ? `:${rc.affected_lines[i]}` : ''}`)
    .join(', ');
  return (
    <div className="dp-detail">
      <div className="dp-rc-head">
        <span className="dp-chip">{rc?.classification || rc?.category || 'CODE_BUG'}</span>
        <span className="dp-chip dp-chip-conf">Confidence {pct}%</span>
      </div>
      {location && <Row k="Location" v={location} mono />}
      {(rc?.affected_functions?.length || 0) > 0 && (
        <Row k="Function" v={rc.affected_functions.join(', ')} mono />
      )}
      {rc?.root_cause && (
        <div className="dp-rc-block">
          <div className="dp-detail-title">Conclusion</div>
          <p>{rc.root_cause}</p>
        </div>
      )}
      {(rc?.evidence?.length || 0) > 0 && (
        <div className="dp-rc-block">
          <div className="dp-detail-title">Evidence</div>
          {rc.evidence.map((e, i) => (
            <p key={i} className="dp-evidence">
              — {e}
            </p>
          ))}
        </div>
      )}
      {rc?.recommended_action && (
        <div className="dp-rc-block">
          <div className="dp-detail-title">Recommended remediation</div>
          <p>{rc.recommended_action}</p>
        </div>
      )}
    </div>
  );
}

function FixCard({ diff, onReviewDiff }) {
  if (!diff?.present) {
    return (
      <div className="dp-detail">
        <p className="dp-dim">Patch not available yet.</p>
      </div>
    );
  }
  return (
    <div className="dp-detail">
      <Row k="Summary" v={diff.summary} />
      <div className="dp-detail-title">Files changed</div>
      {(diff.files_changed || []).map((f) => (
        <div className="dp-file" key={f}>
          <FileCode2 size={12} />
          <span>{f}</span>
        </div>
      ))}
      <div className="dp-rc-head" style={{ marginTop: 8 }}>
        {diff.risk && <span className="dp-chip">Risk: {diff.risk}</span>}
      </div>
      {diff.reason && <p className="dp-dim" style={{ marginTop: 6 }}>{diff.reason}</p>}
      {onReviewDiff && (
        <button type="button" className="dp-link" onClick={onReviewDiff}>
          Review diff in editor →
        </button>
      )}
    </div>
  );
}

function SandboxDetail({ sandbox }) {
  if (!sandbox?.present) {
    return (
      <div className="dp-detail">
        <p className="dp-dim">Verification has not run yet.</p>
      </div>
    );
  }
  return (
    <div className="dp-detail">
      <div className={`dp-sandbox-banner ${sandbox.passed ? 'is-ok' : 'is-bad'}`}>
        {sandbox.passed ? 'Verification passed' : 'Verification failed'}
      </div>
      {(sandbox.steps || []).map((s, i) => (
        <div className="dp-test" key={i}>
          {s.passed ? (
            <CheckCircle2 size={12} className="dp-ok" />
          ) : (
            <XCircle size={12} className="dp-bad" />
          )}
          <span>{s.name || `Step ${i + 1}`}</span>
          {s.detail && <small title={s.detail}>{truncate(s.detail)}</small>}
        </div>
      ))}
      {sandbox.logs && <pre className="dp-code">{truncate(sandbox.logs, 600)}</pre>}
      {!sandbox.passed && sandbox.error && (
        <p className="dp-dim dp-bad-text">{sandbox.error}</p>
      )}
    </div>
  );
}

function StepDetail({ stage, run, runContext, runDiff, runSandbox, onOpenFile, onReviewDiff }) {
  const files = runContext?.implicated_files || [];
  switch (stage.id) {
    case 'error': {
      const d = run?.detection || {};
      return (
        <div className="dp-detail">
          <Row k="Endpoint" v={`${d.method || ''} ${d.endpoint || ''}`.trim() || '—'} mono />
          <Row k="HTTP status" v={d.status_code != null ? String(d.status_code) : '—'} />
          <Row k="Source" v={d.source || 'production'} />
          {d.error_message && <Row k="Error" v={d.error_message} mono />}
        </div>
      );
    }
    case 'logs': {
      const d = run?.detection || {};
      const lines = String(d.raw_logs || '').split('\n').filter(Boolean).length;
      return (
        <div className="dp-detail">
          <Row k="Source" v={d.source || '—'} />
          <Row k="Entries analyzed" v={lines ? String(lines) : '—'} />
        </div>
      );
    }
    case 'trace':
      return (
        <div className="dp-detail">
          <Row k="Result" v={lastMessage(stage)} />
          {runContext?.stack_trace && <pre className="dp-code">{runContext.stack_trace}</pre>}
        </div>
      );
    case 'repo': {
      const conn = (stage.rows || []).find((r) => r.step === 'repository_connected')?.message;
      const disc = (stage.rows || []).find((r) => r.step === 'project_discovered')?.message;
      return (
        <div className="dp-detail">
          <Row k="Workspace" v={conn || '—'} mono />
          {disc && <Row k="Project" v={disc} />}
        </div>
      );
    }
    case 'access':
      return (
        <div className="dp-detail">
          <div className="dp-detail-title">Files identified for reading</div>
          {files.length ? (
            files.map((f) => (
              <button type="button" className="dp-file" key={f} onClick={() => onOpenFile?.(f)}>
                <FileCode2 size={12} />
                <span>{f}</span>
              </button>
            ))
          ) : (
            <p className="dp-dim">No files identified yet.</p>
          )}
        </div>
      );
    case 'read':
      return (
        <div className="dp-detail">
          {(stage.rows || []).map((r) => (
            <button
              type="button"
              className="dp-file"
              key={r.key}
              onClick={() => onOpenFile?.(normalizedTarget(r.message))}
            >
              {r.status === 'done' ? (
                <Check size={12} className="dp-ok" />
              ) : (
                <Loader2 size={12} className="spin" />
              )}
              <span>{r.message}</span>
            </button>
          ))}
        </div>
      );
    case 'context':
      return (
        <div className="dp-detail">
          <p className="dp-dim">{lastMessage(stage) || 'Context assembled.'}</p>
        </div>
      );
    case 'investigate':
      return (
        <div className="dp-detail">
          <p className="dp-dim">Tracing the execution path through the collected evidence and source.</p>
        </div>
      );
    case 'cause':
      return <RootCauseCard rc={run?.root_cause || {}} />;
    case 'fix':
    case 'review':
      return <FixCard diff={runDiff} onReviewDiff={onReviewDiff} />;
    case 'apply': {
      const applied =
        run?.applied_files?.length
          ? run.applied_files
          : runDiff?.applied_files?.length
            ? runDiff.applied_files
            : runDiff?.files_changed || [];
      return (
        <div className="dp-detail">
          <Row k="Result" v={lastMessage(stage)} />
          {applied.length > 0 && <div className="dp-detail-title">Files changed</div>}
          {applied.map((f) => (
            <button type="button" className="dp-file" key={f} onClick={() => onOpenFile?.(f)}>
              <FileCode2 size={12} />
              <span>{f}</span>
            </button>
          ))}
        </div>
      );
    }
    case 'sandbox':
    case 'verify':
      return <SandboxDetail sandbox={runSandbox} />;
    case 'delivery': {
      const pr = (stage.rows || []).find((r) => r.step === 'pr_created')?.message;
      const sha = (stage.rows || []).find(
        (r) => r.step === 'local_commit' || r.step === 'commit_created'
      )?.message;
      return (
        <div className="dp-detail">
          {sha && <Row k="Commit" v={sha} mono />}
          {pr && <Row k="Pull request" v={pr} mono />}
        </div>
      );
    }
    default:
      return (
        <div className="dp-detail">
          <p className="dp-dim">{lastMessage(stage) || 'Completed'}</p>
        </div>
      );
  }
}

/* ---------------------------------------------------------------------------
 * Panel
 * ------------------------------------------------------------------------- */

export default function APIDoctorPanel({
  activeRun,
  runContext,
  runDiff,
  runSandbox,
  runPR,
  stages = [],
  isDiagnosing = false,
  isRunActionPending = false,
  onKeepChanges,
  onRejectChanges,
  onApplyFix,
  onRestart,
  onCommitChanges,
  onCreatePR,
  onApproveFileRead,
  onNewDiagnosis,
  onStartDiagnosis,
  onOpenIngestModal,
  doctorWidth = 420,
  projectProfile,
  isDoctorOpen = true,
  setIsDoctorOpen,
  selectedFile,
  setSelectedFile,
  setIsDiffMode,
  demoMode = false,
  onRunDemoScenario,
  isDemoPending = false,
}) {
  const bodyRef = useRef(null);
  const [expanded, setExpanded] = useState(null);

  // Elapsed time for the step currently buffering.
  const [, setTick] = useState(0);
  const startsRef = useRef(new Map());
  const hasBuffering = stages.some((s) => s.phase === 'buffering');
  useEffect(() => {
    if (!hasBuffering) return undefined;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [hasBuffering]);
  useEffect(() => {
    if (!stages.length) startsRef.current.clear();
    for (const s of stages) {
      if (s.phase === 'buffering' && !startsRef.current.has(s.key)) {
        startsRef.current.set(s.key, Date.now());
      }
    }
  }, [stages]);

  // Keep the newest operation in view as steps reveal themselves.
  useEffect(() => {
    if (!bodyRef.current || !activeRun?.status) return;
    bodyRef.current.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' });
  }, [stages.length, activeRun?.status, expanded]);

  const isAwaitingRead = activeRun?.status === 'AWAITING_FILE_READ_APPROVAL';
  const isAwaitingFix = activeRun?.status === 'AWAITING_FIX_APPROVAL';
  const rejected = activeRun?.status === 'REQUIRES_HUMAN_REVIEW';
  const failed =
    Boolean(runSandbox?.present && runSandbox.passed === false) ||
    Boolean(activeRun?.status?.includes('FAIL')) ||
    activeRun?.status === 'CANCELLED';
  const verified =
    Boolean(runSandbox?.passed) ||
    activeRun?.status === 'FIX_VERIFIED' ||
    activeRun?.status === 'PR_READY' ||
    activeRun?.status === 'PR_CREATED';

  const filesToApprove = runContext?.implicated_files || [];
  const currentOp = stages.find((s) => s.phase === 'buffering');
  const rejectedSourceAccess = (activeRun?.activity || []).some(
    (e) => e.step === 'file_read_approval' && e.status === 'failed'
  );
  const headerStatus = isAwaitingRead || isAwaitingFix
    ? 'WAITING'
    : failed
      ? 'FAILED'
      : verified
        ? 'COMPLETE'
        : isDiagnosing
          ? 'DIAGNOSING'
          : 'READY';

  const elapsedOf = (stage) => {
    const start = startsRef.current.get(stage.key);
    if (!start) return '';
    const total = Math.max(0, Math.floor((Date.now() - start) / 1000));
    const mm = String(Math.floor(total / 60)).padStart(2, '0');
    const ss = String(total % 60).padStart(2, '0');
    return `${mm}:${ss}`;
  };

  if (!isDoctorOpen) return null;

  return (
    <aside className="doctor-panel" style={{ width: `${doctorWidth}px` }}>
      <header className="dp-header">
        <div className="dp-header-title">
          <ShieldCheck size={15} />
          <span className="dp-brand">API DOCTOR</span>
          {activeRun && <span className="dp-brand-sub">LIVE DIAGNOSIS</span>}
        </div>
        <div className="dp-header-right">
          <span className={`dp-status is-${headerStatus.toLowerCase()}`}>{headerStatus}</span>
          {activeRun && (
            <button
              type="button"
              className="dp-icon-btn"
              title="Start a new diagnosis"
              onClick={onNewDiagnosis}
            >
              <RotateCcw size={13} />
            </button>
          )}
          <button
            type="button"
            className="dp-icon-btn"
            title="Collapse panel"
            onClick={() => setIsDoctorOpen(false)}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </header>

      {!activeRun ? (
        <div className="dp-idle">
          <div className="dp-idle-main">
            <div className="dp-kicker">DIAGNOSTIC ENGINE</div>
            <h2>Ready to investigate</h2>
            <p>
              API Doctor reproduces the failure, collects live evidence from your
              logs and source, isolates the root cause and proposes a verified fix —
              one step at a time.
            </p>
            {demoMode && onRunDemoScenario ? (
              <>
                <button
                  type="button"
                  className="dp-cta"
                  disabled={isDemoPending}
                  onClick={() => onRunDemoScenario('external_api')}
                >
                  <Play size={14} fill="currentColor" />
                  <span>{isDemoPending ? 'Starting demo…' : 'Run Demo Diagnosis'}</span>
                </button>
                <button type="button" className="dp-cta-secondary" onClick={onOpenIngestModal}>
                  Paste error / stack trace
                </button>
              </>
            ) : (
              <>
                <button type="button" className="dp-cta" onClick={onStartDiagnosis}>
                  <Play size={14} fill="currentColor" />
                  <span>Start Diagnosis</span>
                </button>
                <button type="button" className="dp-cta-secondary" onClick={onOpenIngestModal}>
                  Paste error / stack trace
                </button>
              </>
            )}
          </div>
          <div className="dp-idle-context">
            <div className="dp-kicker">Current context</div>
            <div className="dp-row">
              <span className="dp-row-k">Target</span>
              <span className="dp-row-v is-mono">{selectedFile || 'Workspace'}</span>
            </div>
            <div className="dp-row">
              <span className="dp-row-k">Framework</span>
              <span className="dp-row-v">
                {projectProfile?.framework || projectProfile?.language || 'Auto-detected'}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="dp-live">
          <div className="dp-body" ref={bodyRef}>
            <div className="dp-steps">
              {stages.map((stage, index) => {
                const state = displayState(stage);
                const message = displayMessage(stage, activeRun, runDiff, runSandbox);
                const isExpanded = expanded === stage.key;
                const isLast = index === stages.length - 1;
                return (
                  <div
                    key={stage.key}
                    className={`dp-step is-${state}${isExpanded ? ' is-open' : ''}`}
                  >
                    <div className="dp-step-rail">
                      <StepIcon state={state} />
                      {!isLast && <span className="dp-step-line" />}
                    </div>
                    <div className="dp-step-main">
                      <button
                        type="button"
                        className="dp-step-card"
                        onClick={() => setExpanded(isExpanded ? null : stage.key)}
                        aria-expanded={isExpanded}
                      >
                        <div className="dp-step-head">
                          <span className="dp-step-title">{stage.label}</span>
                          <span className="dp-step-state">{state}</span>
                        </div>
                        <div className="dp-step-msg">
                          <span className={state === 'running' ? 'dp-step-working' : ''}>{message}</span>
                        </div>
                        {state === 'running' && (
                          <div className="dp-step-running">
                            <span className="dp-ellipsis" />
                            <span className="dp-elapsed">{elapsedOf(stage)}</span>
                          </div>
                        )}
                      </button>
                      {isExpanded && (
                        <StepDetail
                          stage={stage}
                          run={activeRun}
                          runContext={runContext}
                          runDiff={runDiff}
                          runSandbox={runSandbox}
                          onOpenFile={setSelectedFile}
                          onReviewDiff={() => setIsDiffMode(true)}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <footer className="dp-footer">
            {isAwaitingRead && (
              <div className="dp-approval">
                <div className="dp-approval-title">
                  <span className="dp-wait-dot" /> Waiting for approval
                </div>
                <p className="dp-approval-text">
                  API Doctor wants to read {filesToApprove.length} source file
                  {filesToApprove.length === 1 ? '' : 's'} to continue the investigation:
                </p>
                <ul className="dp-approval-files">
                  {filesToApprove.slice(0, 4).map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                  {filesToApprove.length > 4 && <li>+ {filesToApprove.length - 4} more</li>}
                </ul>
                <div className="dp-approval-actions">
                  <button
                    type="button"
                    className="dp-btn is-ghost"
                    disabled={isRunActionPending}
                    onClick={() => onApproveFileRead(false)}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    className="dp-btn is-primary"
                    disabled={isRunActionPending}
                    onClick={() => onApproveFileRead(true)}
                  >
                    {isRunActionPending ? <Loader2 size={13} className="spin" /> : <Check size={13} />}
                    <span>Approve &amp; Continue</span>
                  </button>
                </div>
              </div>
            )}

            {isAwaitingFix && (
              <div className="dp-approval">
                <div className="dp-approval-title">
                  <span className="dp-wait-dot" /> Waiting for approval
                </div>
                <p className="dp-approval-text dp-approval-summary">
                  {runDiff?.summary || 'A proposed repair is ready for review.'}
                </p>
                <div className="dp-approval-meta">
                  {(runDiff?.files_changed || []).length > 0 && (
                    <span>{runDiff.files_changed.length} file(s) changed</span>
                  )}
                  {runDiff?.risk && <span>Risk: {runDiff.risk}</span>}
                </div>
                <div className="dp-approval-actions">
                  <button
                    type="button"
                    className="dp-btn is-ghost"
                    disabled={isRunActionPending}
                    onClick={onRejectChanges}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    className="dp-btn is-ghost"
                    onClick={() => setIsDiffMode(true)}
                  >
                    Review Diff
                  </button>
                  <button
                    type="button"
                    className="dp-btn is-primary"
                    disabled={isRunActionPending}
                    onClick={onKeepChanges}
                  >
                    {isRunActionPending ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
                    <span>Keep Changes</span>
                  </button>
                </div>
              </div>
            )}

            {!isAwaitingRead && !isAwaitingFix && rejected && (
              <div className="dp-approval is-rejected">
                <div className="dp-approval-title">
                  <X size={13} /> {rejectedSourceAccess ? 'Source access rejected' : 'Patch rejected'}
                </div>
                <p className="dp-approval-text">
                  {rejectedSourceAccess
                    ? 'No source files were read. Start a fresh diagnosis when ready.'
                    : 'Workspace left untouched. Start a fresh diagnosis when ready.'}
                </p>
                <div className="dp-approval-actions">
                  <button type="button" className="dp-btn is-primary" onClick={onNewDiagnosis}>
                    <RotateCcw size={13} />
                    <span>New Diagnosis</span>
                  </button>
                </div>
              </div>
            )}

            {!isAwaitingRead && !isAwaitingFix && !rejected && failed && (
              <div className="dp-approval is-failed">
                <div className="dp-approval-title">
                  <XCircle size={13} /> Diagnosis failed
                </div>
                <p className="dp-approval-text">
                  {runSandbox?.error || activeRun?.error_message || 'The proposed change did not pass verification.'}
                </p>
                <div className="dp-approval-actions">
                  <button type="button" className="dp-btn is-primary" onClick={onRestart}>
                    <RotateCcw size={13} />
                    <span>Run Fresh Diagnosis</span>
                  </button>
                </div>
              </div>
            )}

            {!isAwaitingRead && !isAwaitingFix && !rejected && !failed && verified && (
              <div className="dp-result">
                <div className="dp-result-head">
                  <CheckCircle2 size={15} className="dp-ok" />
                  <span>Repair verified</span>
                </div>
                {runDiff?.summary && <p className="dp-result-summary">{runDiff.summary}</p>}
                <div className="dp-result-actions">
                  {runDiff?.present && !runDiff.applied && (
                    <button type="button" className="dp-btn is-primary" onClick={onApplyFix}>
                      <FileCode2 size={13} />
                      <span>Apply to Workspace</span>
                    </button>
                  )}
                  {!activeRun.commit_sha && (
                    <button type="button" className="dp-btn" onClick={onCommitChanges}>
                      <GitCommit size={13} />
                      <span>Commit</span>
                    </button>
                  )}
                  {!runPR?.present && (
                    <button type="button" className="dp-btn" onClick={onCreatePR}>
                      <GitPullRequest size={13} />
                      <span>Create PR</span>
                    </button>
                  )}
                  {runPR?.present && (
                    <a className="dp-btn is-primary" href={runPR.pr_url} target="_blank" rel="noreferrer">
                      Open Pull Request ↗
                    </a>
                  )}
                  <button type="button" className="dp-btn is-ghost" onClick={onNewDiagnosis}>
                    <RotateCcw size={13} />
                    <span>New Diagnosis</span>
                  </button>
                </div>
              </div>
            )}

            {!isAwaitingRead && !isAwaitingFix && !rejected && !failed && !verified && (
              <div className="dp-working">
                <Loader2 size={12} className="spin" />
                <span className="dp-working-text">
                  {currentOp ? displayMessage(currentOp, activeRun, runDiff, runSandbox) : 'Working…'}
                </span>
              </div>
            )}
          </footer>
        </div>
      )}
    </aside>
  );
}
