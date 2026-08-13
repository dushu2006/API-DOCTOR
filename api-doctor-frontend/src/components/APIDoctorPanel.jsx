import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Stethoscope,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  XCircle,
  Clock,
  GitPullRequest,
  GitCommit,
  GitBranch,
  Check,
  ArrowUpRight,
  ArrowDown,
  Plus,
  Server,
  FileText,
  History,
  RefreshCw,
  AlertTriangle,
  BadgeCheck,
  Siren,
  Zap,
  FolderSearch,
  Search,
  Wrench,
  FlaskConical
} from 'lucide-react';
import './doctor.css';

/* ---------------------------------------------------------------------------
 * API Doctor agent panel — retro operator console.
 * Visual language mirrors the reference diagnosis report: thin framed cards,
 * sunken consoles, circled status checks, beveled CTAs, tracked kickers —
 * and the agent's work is presented as a numbered STEP-BY-STEP ANALYSIS:
 * one phase after the other, each filling in live as the pipeline runs.
 * All behaviour (props/handlers) is unchanged from the previous panel.
 * ------------------------------------------------------------------------- */

const STEP_LABELS = {
  pipeline: 'Diagnosis pipeline',
  pipeline_error: 'Pipeline error',
  repository_check: 'Verifying repository workspace',
  repository_connected: 'Repository connected',
  github_connected: 'Repository connected',
  repository_verified: 'Repository verified',
  repository_synced: 'Workspace state checked',
  repository_synchronized: 'Project synchronized',
  project_discovered: 'Project discovered',
  logs_retrieved: 'Logs retrieved',
  error_detected: 'Error detected',
  duplicate_suppressed: 'Duplicate incident suppressed',
  rediagnosis_requested: 'Fresh diagnosis requested',
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
  fix_regenerating: 'Regenerating fix',
  fix_approval: 'Fix approval',
  fix_rejected: 'Patch rejected',
  diff_ready: 'Proposed diff ready',
  changes_applied: 'Applying changes to workspace',
  changes_rolled_back: 'Workspace rollback',
  workspace_updated: 'Workspace updated',
  sandbox_started: 'Sandbox verification',
  tests_started: 'Running tests',
  test_passed: 'Tests passed',
  fix_verified: 'Fix verified',
  human_review: 'Human review',
  reproduce_failure: 'Reproduce failure',
  apply_patch: 'Apply patch',
  run_tests: 'Run test suite',
  run_build: 'Build / syntax check',
  health_check: 'Service health check',
  verify_fix: 'Verify fix',
  local_commit: 'Local commit',
  branch_created: 'Repair branch created',
  commit_created: 'Commit created',
  pr_created: 'Pull request created'
};

/* ---------------------------------------------------------------------------
 * The agent pipeline, as a fixed ordered sequence of phases. Each phase maps
 * the real backend events (SSE / incident activity) into ONE numbered block,
 * rendered one after the other — the step-by-step analysis structure.
 * ------------------------------------------------------------------------- */
const PHASES = [
  {
    id: 'detect',
    title: 'Failure Detection',
    icon: Siren,
    steps: ['logs_retrieved', 'error_detected', 'duplicate_suppressed', 'rediagnosis_requested']
  },
  {
    id: 'workspace',
    title: 'Workspace & Repository',
    icon: GitBranch,
    steps: [
      'repository_check',
      'repository_connected',
      'github_connected',
      'repository_verified',
      'repository_synced',
      'repository_synchronized',
      'project_discovered'
    ]
  },
  {
    id: 'trace',
    title: 'Stack Trace Analysis',
    icon: Zap,
    steps: ['stack_trace_parsed']
  },
  {
    id: 'files',
    title: 'Relevant File Identification',
    icon: FolderSearch,
    steps: ['collecting_context', 'relevant_source_identified', 'files_to_read', 'file_read_approval']
  },
  {
    id: 'read',
    title: 'Source Reading',
    icon: FileText,
    steps: ['file_read']
  },
  {
    id: 'root',
    title: 'Root Cause Investigation',
    icon: Search,
    steps: ['investigating', 'investigation_started', 'root_cause_identified']
  },
  {
    id: 'fix',
    title: 'Fix Generation',
    icon: Wrench,
    steps: ['fix_generated', 'fix_regenerating', 'fix_approval', 'fix_rejected', 'diff_ready']
  },
  {
    id: 'verify',
    title: 'Sandbox Verification',
    icon: FlaskConical,
    steps: [
      'sandbox_started',
      'tests_started',
      'reproduce_failure',
      'apply_patch',
      'run_tests',
      'run_build',
      'health_check',
      'verify_fix',
      'test_passed',
      'fix_verified',
      'changes_applied',
      'changes_rolled_back',
      'workspace_updated',
      'pipeline_error'
    ]
  },
  {
    id: 'deliver',
    title: 'Delivery',
    icon: GitPullRequest,
    steps: ['local_commit', 'branch_created', 'commit_created', 'pr_created', 'human_review']
  }
];

// Steps that repeat with a different target per event (one row per file).
const REPEATING_STEPS = new Set(['file_read']);

function phaseState(rows) {
  if (!rows.length) return 'idle';
  const failed = rows.some(r => r.status === 'failed' || r.status === 'cancelled');
  const working = rows.some(r => r.status === 'running' || r.status === 'pending' || r.status === 'paused');
  if (failed) return 'failed';
  if (working) return 'working';
  return 'done';
}

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
        time
      });
    }
  }
  return rows;
}

/* Small building blocks ---------------------------------------------------- */

function Kicker({ children }) {
  return <div className="dr-kicker">{children}</div>;
}

function StatusDot({ tone }) {
  // tone: ok | bad | run | wait | idle
  if (tone === 'run') {
    return (
      <span className="dr-circle" style={{ background: '#101114', border: '1px solid #1d1f25' }}>
        <span className="dr-pulse" style={{ width: 7, height: 7 }} />
      </span>
    );
  }
  if (tone === 'wait') {
    return (
      <span className="dr-circle dr-circle-wait">
        <Clock size={10} />
      </span>
    );
  }
  if (tone === 'bad') {
    return (
      <span className="dr-circle dr-circle-bad">
        <XCircle size={11} />
      </span>
    );
  }
  if (tone === 'idle') {
    return <span className="dr-circle" style={{ border: '1px solid #3a3d45', background: '#101114' }} />;
  }
  return (
    <span className="dr-circle dr-circle-ok">
      <Check size={11} strokeWidth={3} />
    </span>
  );
}

function PhaseRow({ row }) {
  const isRunning = row.status === 'running';
  const isPending = row.status === 'pending' || row.status === 'paused';
  const isFailed = row.status === 'failed' || row.status === 'cancelled';
  const detail = row.message && row.message !== row.label ? row.message : '';
  const tone = isRunning ? 'run' : isPending ? 'wait' : isFailed ? 'bad' : 'ok';
  const rowClass = isFailed
    ? 'dr-phase-row dr-phase-row-failed'
    : isRunning
      ? 'dr-phase-row dr-phase-row-running'
      : 'dr-phase-row';

  return (
    <div className={rowClass}>
      <StatusDot tone={tone} />
      <div className="dr-phase-row-main">
        <span className="dr-phase-row-label">
          {row.label}{isRunning && !detail ? '…' : ''}
        </span>
        {detail && <span className="dr-phase-row-detail">{detail}</span>}
      </div>
      <span className="dr-phase-row-time">{row.time ? row.time.toLocaleTimeString() : ''}</span>
    </div>
  );
}

/* Main panel --------------------------------------------------------------- */

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
  onRediagnose,
  onCommitChanges,
  onCreatePR,
  onApproveFileRead,
  onSelectIncident,
  onNewDiagnosis,
  onSyncRender,
  onOpenIngestModal,
  doctorWidth = 380,
  isDoctorOpen = true,
  setIsDoctorOpen,
  setSelectedFile,
  setIsDiffMode,
  demoMode = false,
  onRunDemoScenario,
  isDemoPending = false
}) {
  const [historyOpen, setHistoryOpen] = useState(false);

  const timelineRows = useMemo(() => buildTimeline(timelineEvents), [timelineEvents]);

  const phases = useMemo(
    () =>
      PHASES.map(def => {
        const rows = timelineRows.filter(row => def.steps.includes(row.step));
        return { ...def, rows, state: phaseState(rows) };
      }),
    [timelineRows]
  );

  const rootCause = activeIncident?.root_cause;
  const confidence = Number.isFinite(Number(rootCause?.confidence))
    ? Math.min(1, Math.max(0, Number(rootCause.confidence)))
    : null;
  const confidencePercent = confidence === null ? null : Math.round(confidence * 100);

  /* ----- chat-style auto-scroll ------------------------------------------
   * The panel behaves like an AI chat console: while the agent streams,
   * the view is pinned to the newest output so the latest step is always
   * visible. Scrolling up releases the pin (reading history is never yanked
   * away); scrolling back near the bottom — or clicking the "new activity"
   * pill — re-pins it. Starting a diagnosis always re-pins and jumps to the
   * live edge, like sending a chat message.
   * ---------------------------------------------------------------------- */
  const bodyRef = useRef(null);
  const actionCardRef = useRef(null);
  const [pinned, setPinned] = useState(true); // body follows the live output
  const stickRef = useRef(true);              // instant mirror of `pinned` for handlers/effects
  const lastIncidentId = useRef(null);
  const wasDiagnosing = useRef(false);

  const lastRow = timelineRows[timelineRows.length - 1];

  // A signature of "what the latest row is doing" so effects fire when the
  // last event flips running -> done, not only when rows are added.
  const streamSignature = `${timelineRows.length}|${lastRow?.status || ''}|${lastRow?.message || ''}`;

  const setStick = (value) => {
    stickRef.current = value;
    setPinned(prev => (prev === value ? prev : value));
  };
  const tailBody = (behavior = 'auto') => {
    const el = bodyRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  };

  // Statuses that mean "the agent is (or may still be) working right now"
  // — those incidents open pinned to the live edge instead of the top.
  const isLiveStatus = status =>
    Boolean(status) && !/VERIFIED|READY|CREATED|FAILED|CANCELLED|REQUIRES_HUMAN|REACHED/.test(status);

  useEffect(() => {
    // Incident switched: a live one opens pinned to the newest activity
    // (chat behaviour); a finished one opens at the top of its report.
    if (activeIncident?.id !== lastIncidentId.current) {
      lastIncidentId.current = activeIncident?.id || null;
      if (activeIncident && (isDiagnosing || isLiveStatus(activeIncident.status))) {
        setStick(true);
        requestAnimationFrame(() => { tailBody(); });
      } else {
        setStick(false);
        if (bodyRef.current) bodyRef.current.scrollTop = 0;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIncident?.id]);

  useEffect(() => {
    // A diagnosis run starting (including a re-run on the same incident)
    // always re-pins and jumps to the live stream.
    if (isDiagnosing && !wasDiagnosing.current) {
      setStick(true);
      requestAnimationFrame(() => { tailBody(); });
    }
    wasDiagnosing.current = Boolean(isDiagnosing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDiagnosing]);

  useEffect(() => {
    // New agent output arrived: follow it only while pinned.
    if (stickRef.current) tailBody();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamSignature]);

  useEffect(() => {
    // Final report sections (verdict, suite results, PR card) also grow the
    // feed — keep following them while pinned even if no new row streamed.
    if (stickRef.current) tailBody();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIncident?.status, incidentSandbox, incidentPR]);

  // When an actionable gate (file-read approval / fix approval) appears,
  // bring it into view once so the decision never waits below the fold.
  const actionableStatus = activeIncident?.status;
  useEffect(() => {
    if (
      (actionableStatus === 'AWAITING_FILE_READ_APPROVAL' || actionableStatus === 'AWAITING_FIX_APPROVAL') &&
      actionCardRef.current
    ) {
      actionCardRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [actionableStatus]);

  const NEAR_BOTTOM_PX = 72;
  const handleBodyScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    setStick(el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX);
  };
  const jumpToLatest = () => {
    setStick(true);
    tailBody('smooth');
  };
  const streamLive = Boolean(isDiagnosing) || lastRow?.status === 'running' ||
    activeIncident?.status === 'AWAITING_FILE_READ_APPROVAL' ||
    activeIncident?.status === 'AWAITING_FIX_APPROVAL';

  if (!isDoctorOpen) return null;

  /* ----- derived state ---------------------------------------------------- */
  const classification = rootCause ? (rootCause.classification || rootCause.category || 'CODE_BUG') : null;

  const appliedFiles = activeIncident?.applied_files || activeIncident?.fix_proposal?.applied_files || [];
  const commitSha = activeIncident?.commit_sha || activeIncident?.fix_proposal?.commit_sha || '';
  const isAwaitingFix = activeIncident?.status === 'AWAITING_FIX_APPROVAL';
  const isAwaitingFileRead = activeIncident?.status === 'AWAITING_FILE_READ_APPROVAL';
  const isVerified = Boolean(incidentSandbox?.passed);
  const wasRolledBack = timelineRows.some(r => r.step === 'changes_rolled_back');
  const applyFailure = [...timelineRows].reverse().find(
    row => row.step === 'changes_applied' && row.status === 'failed'
  ) || [...(activeIncident?.activity || [])].reverse().find(
    event => event.step === 'changes_applied' && event.status === 'failed'
  );
  const verificationFailed = Boolean(incidentSandbox?.present && incidentSandbox.passed === false);
  const needsFreshDiagnosis = appliedFiles.length === 0 && (
    Boolean(applyFailure) || (!isAwaitingFix && (verificationFailed || wasRolledBack))
  );

  const branchRow = [...timelineRows].reverse().find(r => r.step === 'branch_created' && r.status === 'done')
    || [...(activeIncident?.activity || [])].reverse().find(e => e.step === 'branch_created' && e.status === 'done');
  const branchName = incidentPR?.branch || branchRow?.message || '';
  const prPresent = Boolean(incidentPR?.present);
  const prUrl = incidentPR?.pr_url || '';
  const fixTitle = incidentDiff?.summary || activeIncident?.fix_proposal?.summary || 'API Doctor Repair';

  const sandboxSteps = Array.isArray(incidentSandbox?.steps) ? incidentSandbox.steps : [];
  const passedCount = sandboxSteps.filter(s => s?.passed).length;
  const failedCount = sandboxSteps.filter(s => s && s.passed === false).length;
  const suiteTotal = sandboxSteps.length;
  const suitePercent = suiteTotal ? Math.round((passedCount / suiteTotal) * 100) : (incidentSandbox?.passed ? 100 : 0);
  const regressionStep = sandboxSteps.find(s => String(s?.name || '').includes('regression'))
    || sandboxSteps.find(s => String(s?.name || '') === 'verify_fix');
  const regressionPassed = regressionStep ? Boolean(regressionStep.passed) : Boolean(incidentSandbox?.passed);

  // Headline status line, mirroring the reference report.
  const headline = (() => {
    if (!activeIncident) return null;
    if (isVerified) return { tone: 'ok', text: 'FIX VERIFIED' };
    if (verificationFailed) return { tone: 'bad', text: 'VERIFICATION FAILED' };
    if (isAwaitingFix) return { tone: 'wait', text: 'AWAITING FIX APPROVAL' };
    if (isAwaitingFileRead) return { tone: 'wait', text: 'AWAITING FILE READ APPROVAL' };
    if (isDiagnosing) return { tone: 'run', text: 'DIAGNOSING…' };
    if (activeIncident.status?.includes('FAIL')) return { tone: 'bad', text: String(activeIncident.status).replace(/_/g, ' ') };
    if (prPresent) return { tone: 'ok', text: 'PULL REQUEST READY' };
    return { tone: 'wait', text: String(activeIncident.status || 'RECEIVED').replace(/_/g, ' ') };
  })();

  const historyItems = (incidentsList || []).filter(inc => inc.id !== activeIncident?.id);
  const showGitOps = Boolean(branchName || commitSha || prPresent || (isVerified && appliedFiles.length && !commitSha) || (isVerified && !prPresent));
  const implicatedFiles = incidentContext?.implicated_files?.length
    ? incidentContext.implicated_files
    : (activeIncident?.context?.affected_files || []);

  const phaseColor = state =>
    state === 'working' ? 'var(--dr-amber)'
      : state === 'failed' ? 'var(--dr-red)'
        : state === 'done' ? 'var(--dr-green)'
          : 'var(--dr-faint)';

  const phaseStateLabel = {
    idle: 'Not started',
    working: 'In progress',
    done: 'Completed',
    failed: 'Failed'
  };

  /* ----- per-phase analysis results (rendered inside each step) --------- */
  const renderPhaseExtras = (phaseId) => {
    switch (phaseId) {
      case 'files': {
        if (isAwaitingFileRead) {
          return (
            <div ref={actionCardRef} className="dr-step-inset dr-step-inset-gate">
              <Kicker><span style={{ color: 'var(--dr-amber)' }}>APPROVAL REQUIRED — NOTHING READ YET</span></Kicker>
              <p style={{ fontSize: 11, color: 'var(--dr-dim)', margin: '8px 0 10px', lineHeight: 1.5 }}>
                The agent identified these files and wants to read them. Nothing is read until you approve.
              </p>
              <div className="dr-well dr-scroll-thin" style={{ padding: '6px 8px', marginBottom: 12, maxHeight: 120, overflowY: 'auto' }}>
                {implicatedFiles.map(filePath => (
                  <div key={filePath} style={{ padding: '2px 0', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--dr-text)' }}>
                    <ChevronRight size={10} style={{ marginRight: 4, verticalAlign: 'middle', color: 'var(--dr-amber)' }} />
                    {filePath}
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button disabled={isIncidentActionPending} onClick={() => onApproveFileRead(true)} className="dr-btn dr-btn-green" style={{ flex: 1, padding: '7px 10px' }}>
                  <Check size={13} strokeWidth={3} />
                  <span>{isIncidentActionPending ? 'Recording…' : 'Approve Reading'}</span>
                </button>
                <button disabled={isIncidentActionPending} onClick={() => onApproveFileRead(false)} className="dr-btn" style={{ flex: 1, padding: '7px 10px' }}>
                  Deny
                </button>
              </div>
            </div>
          );
        }
        if (implicatedFiles.length > 0) {
          return (
            <div className="dr-well" style={{ marginTop: 2 }}>
              {implicatedFiles.map(filePath => (
                <div key={filePath} className="dr-file-row" onClick={() => setSelectedFile(filePath)}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <Check size={11} strokeWidth={3} style={{ color: 'var(--dr-green)', flexShrink: 0 }} />
                    <span>{filePath}</span>
                  </span>
                  <ChevronRight size={11} style={{ color: 'var(--dr-faint)', flexShrink: 0 }} />
                </div>
              ))}
            </div>
          );
        }
        return null;
      }

      case 'root': {
        if (!rootCause) return null;
        return (
          <div className="dr-step-inset">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: confidencePercent !== null ? 10 : 0 }}>
              <span style={{ fontSize: 10, color: 'var(--dr-dim)', fontFamily: 'var(--font-heading)', letterSpacing: '0.04em', fontWeight: 700 }}>
                {classification ? classification.replace(/_/g, ' ') : 'ROOT CAUSE'}
              </span>
              {confidencePercent !== null && (
                <span style={{ color: 'var(--dr-green)', fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  {confidencePercent}% confidence
                </span>
              )}
            </div>
            {confidencePercent !== null && (
              <div className="dr-meter" style={{ marginBottom: 10 }}>
                <div className="dr-meter-fill" style={{ width: `${confidencePercent}%` }} />
              </div>
            )}
            <p style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 6 }}>
              {rootCause.root_cause || 'Root cause identified.'}
            </p>
            {rootCause.reason && (
              <p style={{ fontSize: 11, color: 'var(--dr-dim)', lineHeight: 1.5, marginBottom: 8 }}>
                {rootCause.reason}
              </p>
            )}
            {rootCause.recommended_action && (
              <div className="dr-notice dr-notice-amber" style={{ marginBottom: 10 }}>
                <strong>Action:</strong> {rootCause.recommended_action}
              </div>
            )}
            {rootCause.affected_files?.[0] && (
              <button onClick={() => setSelectedFile(rootCause.affected_files[0])} className="dr-btn dr-btn-block" style={{ padding: '7px 10px' }}>
                <span>Open {rootCause.affected_files[0]}</span>
                <ArrowUpRight size={12} />
              </button>
            )}
          </div>
        );
      }

      case 'fix': {
        if (!incidentDiff || !incidentDiff.present) return null;
        return (
          <div
            ref={isAwaitingFix && !needsFreshDiagnosis ? actionCardRef : undefined}
            className={`dr-step-inset${isAwaitingFix && !needsFreshDiagnosis ? ' dr-step-inset-gate' : ''}`}
          >
            <div style={{ fontSize: 10, color: 'var(--dr-faint)', fontFamily: 'var(--font-mono)' }}>
              {incidentDiff.files_changed?.length || 1} file(s) changed
            </div>
            <p style={{ fontSize: 12, margin: '6px 0 10px', lineHeight: 1.45 }}>{incidentDiff.summary}</p>

            {appliedFiles.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--dr-green)', fontSize: 12, fontWeight: 700 }}>
                  <StatusDot tone="ok" />
                  <span>Changes applied to workspace</span>
                </div>
                <div className="dr-well" style={{ padding: '6px 10px', fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--dr-dim)' }}>
                  {appliedFiles.map(f => <div key={f}>• {f}</div>)}
                </div>
                <button onClick={() => setIsDiffMode(true)} className="dr-link" style={{ alignSelf: 'flex-start' }}>
                  Review Diff
                </button>
              </div>
            ) : isAwaitingFix && !needsFreshDiagnosis ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Kicker><span style={{ color: 'var(--dr-amber)' }}>REVIEW REQUIRED</span></Kicker>
                <button disabled={isIncidentActionPending} onClick={() => onKeepChanges()} className="dr-btn dr-btn-green dr-btn-block" style={{ padding: '8px 10px' }}>
                  <Check size={13} strokeWidth={3} />
                  <span>{isIncidentActionPending ? 'Applying…' : 'Keep Changes'}</span>
                </button>
                <div style={{ fontSize: 10, color: 'var(--dr-faint)', lineHeight: 1.5 }}>
                  Applies the patch to your workspace, then verifies it in an isolated sandbox copy. If verification fails, the workspace is restored automatically.
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button disabled={isIncidentActionPending} onClick={() => onRejectChanges()} className="dr-btn" style={{ flex: 1, padding: '7px 10px' }}>
                    Reject
                  </button>
                  <button onClick={() => setIsDiffMode(true)} className="dr-link">
                    Review Diff
                  </button>
                </div>
              </div>
            ) : needsFreshDiagnosis ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="dr-notice dr-notice-red">
                  {applyFailure?.message || 'This patch did not pass verification and cannot be applied safely.'}
                </div>
                {onRediagnose && (
                  <button disabled={isIncidentActionPending} onClick={() => onRediagnose()} className="dr-btn dr-btn-blue dr-btn-block" style={{ padding: '8px 10px' }}>
                    <RefreshCw size={13} />
                    <span>{isIncidentActionPending ? 'Starting…' : 'Re-run Diagnosis'}</span>
                  </button>
                )}
                <button onClick={() => setIsDiffMode(true)} className="dr-link" style={{ alignSelf: 'flex-start' }}>
                  Review Previous Diff
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {onApplyFix && isVerified && (
                  <button disabled={isIncidentActionPending} onClick={() => onApplyFix()} className="dr-btn dr-btn-green dr-btn-block" style={{ padding: '8px 10px' }}>
                    <Check size={13} strokeWidth={3} />
                    <span>{isIncidentActionPending ? 'Applying…' : 'Apply to Workspace'}</span>
                  </button>
                )}
                <button onClick={() => setIsDiffMode(true)} className="dr-link" style={{ alignSelf: 'flex-start' }}>
                  Review Diff
                </button>
              </div>
            )}
          </div>
        );
      }

      case 'verify': {
        if (!incidentSandbox || !incidentSandbox.present) {
          if (wasRolledBack) {
            return (
              <div className="dr-notice dr-notice-red">
                Verification failed — your workspace was restored to the original code. Re-run the diagnosis to generate a fresh patch.
              </div>
            );
          }
          return null;
        }
        return (
          <div className="dr-step-inset">
            {wasRolledBack && (
              <div className="dr-notice dr-notice-red" style={{ marginBottom: 10 }}>
                Verification failed — your workspace was restored to the original code. Re-run the diagnosis to generate a fresh patch.
              </div>
            )}
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#c8ccd4', fontFamily: 'var(--font-heading)', letterSpacing: '0.03em' }}>
                Test Suite Result
              </span>
              <span style={{ fontSize: 12, fontWeight: 700, color: failedCount === 0 && incidentSandbox.passed ? 'var(--dr-green)' : 'var(--dr-red)', fontFamily: 'var(--font-mono)' }}>
                {suiteTotal ? `${passedCount} passed · ${failedCount} failed` : incidentSandbox.passed ? 'All checks passed' : 'Checks failed'}
              </span>
            </div>
            <div className="dr-meter" style={{ marginTop: 10 }}>
              <div className={`dr-meter-fill ${failedCount ? 'dr-meter-fill-bad' : ''}`} style={{ width: `${suitePercent}%` }} />
            </div>
            <hr className="dr-rule" style={{ margin: '10px 0' }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11 }}>
              <BadgeCheck size={13} style={{ color: regressionPassed ? 'var(--dr-green)' : 'var(--dr-red)' }} />
              <span style={{ color: 'var(--dr-dim)' }}>Regression:</span>
              <span style={{ fontWeight: 700, color: regressionPassed ? 'var(--dr-green)' : 'var(--dr-red)' }}>
                {regressionPassed ? 'Passed' : 'Failed'}
              </span>
            </div>
            {suiteTotal > 0 && (
              <div className="dr-well" style={{ marginTop: 10, padding: '7px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {sandboxSteps.map(step => (
                  <div key={step.name} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--dr-dim)' }}>
                    {step.passed
                      ? <Check size={11} strokeWidth={3} style={{ color: 'var(--dr-green)' }} />
                      : <XCircle size={11} style={{ color: 'var(--dr-red)' }} />}
                    <span>{String(step.name).replace(/_/g, ' ')}</span>
                  </div>
                ))}
              </div>
            )}
            {!incidentSandbox.passed && incidentSandbox.error && (
              <div className="dr-notice dr-notice-red" style={{ marginTop: 10, fontFamily: 'var(--font-mono)' }}>
                {incidentSandbox.error}
              </div>
            )}
          </div>
        );
      }

      case 'deliver': {
        if (!showGitOps) return null;
        return (
          <div className="dr-step-inset" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {branchName && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <StatusDot tone="ok" />
                <span style={{ color: 'var(--dr-dim)' }}>Branch created:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--dr-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{branchName}</span>
              </div>
            )}
            {commitSha ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <StatusDot tone="ok" />
                <span style={{ color: 'var(--dr-dim)' }}>Changes committed</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--dr-text)' }}>({String(commitSha).slice(0, 7)})</span>
              </div>
            ) : isVerified && appliedFiles.length > 0 && onCommitChanges ? (
              <button disabled={isIncidentActionPending} onClick={onCommitChanges} className="dr-btn dr-btn-block" style={{ padding: '7px 10px' }}>
                <GitCommit size={13} />
                <span>{isIncidentActionPending ? 'Committing…' : 'Commit Changes'}</span>
              </button>
            ) : null}

            {(prPresent || (isVerified && onCreatePR)) && (
              <div className="dr-card" style={{ background: 'var(--dr-surface-2)', padding: 13 }}>
                <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-heading)', letterSpacing: '0.02em', marginBottom: 3 }}>
                  {fixTitle}
                </div>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--dr-faint)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 5 }}>
                  <GitBranch size={11} />
                  <span>{branchName || `api-doctor/fix/${activeIncident.id.slice(0, 8)}`}</span>
                </div>

                {prPresent && (
                  <div style={{ marginBottom: 12 }}>
                    <span className="dr-chip dr-chip-amber">
                      <AlertTriangle size={10} />
                      {incidentPR.status ? String(incidentPR.status) : 'Awaiting human review'}
                    </span>
                  </div>
                )}

                {prPresent ? (
                  <a
                    href={prUrl || '#'}
                    target="_blank"
                    rel="noreferrer"
                    className="dr-btn dr-btn-blue dr-btn-block"
                    style={{ padding: '9px 10px', textDecoration: 'none', fontSize: 12 }}
                  >
                    <ArrowUpRight size={14} />
                    <span>Open Pull Request</span>
                  </a>
                ) : (
                  <button disabled={isIncidentActionPending} onClick={onCreatePR} className="dr-btn dr-btn-blue dr-btn-block" style={{ padding: '9px 10px', fontSize: 12 }}>
                    <GitPullRequest size={14} />
                    <span>{isIncidentActionPending ? 'Creating…' : 'Create Pull Request'}</span>
                  </button>
                )}
              </div>
            )}
          </div>
        );
      }

      default:
        return null;
    }
  };

  return (
    <div
      className="dr-root"
      style={{
        width: `${doctorWidth}px`,
        height: '100%',
        borderLeft: '1px solid #1d1f25',
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
        position: 'relative',
        zIndex: 30
      }}
    >
      {/* Panel header — dotted texture strip like the reference console */}
      <div className="dr-dots" style={{ borderBottom: '1px solid #1d1f25' }}>
        <div style={{ padding: '10px 12px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
            <Stethoscope size={14} style={{ color: '#c8ccd4', flexShrink: 0 }} />
            <span className="dr-kicker" style={{ color: '#c8ccd4' }}>DIAGNOSIS REPORT</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            {activeIncident && (
              isDiagnosing ? (
                <span className="dr-pill-dark" style={{ padding: '3px 8px' }}>
                  <span className="dr-pulse" style={{ width: 6, height: 6 }} />
                  DIAGNOSING
                </span>
              ) : (
                <span className="dr-pill-dark" style={{ padding: '3px 8px' }}>
                  <Check size={10} style={{ color: 'var(--dr-green)' }} />
                  {isVerified ? 'COMPLETE' : 'PAUSED'}
                </span>
              )
            )}
            {activeIncident && (
              <button
                onClick={onNewDiagnosis}
                title="Fresh start — close this report and return to the idle console"
                className="dr-icon-btn"
              >
                <Plus size={15} />
              </button>
            )}
            <button
              onClick={() => setIsDoctorOpen(false)}
              title="Close panel"
              className="dr-icon-btn"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
        <hr className="dr-rule" style={{ margin: '0 12px' }} />
      </div>

      {/* Body */}
      <div
        ref={bodyRef}
        onScroll={handleBodyScroll}
        className="dr-scroll-thin"
        style={{ flex: 1, overflowY: 'auto', padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        {/* ------------------------------------------------ idle state --- */}
        {!activeIncident && (
          <div style={{ textAlign: 'center', padding: '22px 10px' }}>
            <div
              className="dr-well"
              style={{
                width: 52, height: 52, margin: '0 auto 14px',
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--dr-amber)'
              }}
            >
              <Stethoscope size={26} />
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, fontFamily: 'var(--font-heading)', letterSpacing: '0.04em' }}>
              READY TO DIAGNOSE
            </div>
            <p style={{ fontSize: 12, color: 'var(--dr-dim)', marginBottom: 18, lineHeight: 1.55 }}>
              Retrieve real Render logs automatically, or paste production errors manually when the logs come from another source.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button onClick={onSyncRender} className="dr-btn dr-btn-block" style={{ padding: '8px 12px' }}>
                <Server size={13} />
                <span>Sync Render Runtime Logs</span>
              </button>
              <button onClick={onOpenIngestModal} className="dr-btn dr-btn-block" style={{ padding: '8px 12px' }}>
                <FileText size={13} />
                <span>Ingest Production Log / Error</span>
              </button>
              {demoMode && onRunDemoScenario && (
                <button
                  onClick={() => onRunDemoScenario('external_api')}
                  disabled={isDemoPending}
                  className="dr-btn dr-btn-blue dr-btn-block"
                  style={{ padding: '8px 12px' }}
                  title="Run the full step-by-step diagnosis against the built-in demo API with a deterministic bug"
                >
                  <FlaskConical size={13} />
                  <span>{isDemoPending ? 'Starting…' : 'Run Demo Diagnosis'}</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* ------------------------------------------- active incident --- */}
        {activeIncident && (
          <>
            {/* Headline status (FIX VERIFIED / DIAGNOSING / …) */}
            <div className="dr-status-line" style={{
              color: headline.tone === 'ok' ? 'var(--dr-green)' : headline.tone === 'bad' ? 'var(--dr-red)' : headline.tone === 'run' ? 'var(--dr-amber)' : 'var(--dr-text)'
            }}>
              {headline.tone === 'ok' ? (
                <span className="dr-circle dr-circle-lg dr-circle-ok"><Check size={14} strokeWidth={3.5} /></span>
              ) : headline.tone === 'bad' ? (
                <span className="dr-circle dr-circle-lg dr-circle-bad"><XCircle size={14} /></span>
              ) : headline.tone === 'run' ? (
                <span className="dr-circle dr-circle-lg" style={{ background: '#101114', border: '1px solid #1d1f25' }}><span className="dr-pulse" /></span>
              ) : (
                <span className="dr-circle dr-circle-lg dr-circle-wait"><Clock size={13} /></span>
              )}
              <span>{headline.text}</span>
            </div>

            {/* Incident meta strip */}
            <div className="dr-card" style={{ padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                  #{activeIncident.id.slice(0, 8).toUpperCase()}
                </span>
                <span className={`dr-chip ${isVerified || prPresent ? 'dr-chip-green' : activeIncident.status?.includes('FAIL') ? 'dr-chip-red' : 'dr-chip-amber'}`}>
                  {activeIncident.status}
                </span>
              </div>
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--dr-faint)', display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{activeIncident.detection?.source ? `Source: ${activeIncident.detection.source}` : (activeIncident.detection?.endpoint || 'Error ingested')}</span>
                <span>{activeIncident.created_at ? new Date(activeIncident.created_at).toLocaleTimeString() : ''}</span>
              </div>
              {(activeIncident.error_message || activeIncident.detection?.error_message) && (
                <div className="dr-notice dr-notice-red" style={{ marginTop: 8, fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {activeIncident.error_message || activeIncident.detection?.error_message}
                </div>
              )}
            </div>

            {/* ---- STEP-BY-STEP ANALYSIS: one phase after the other ---- */}
            <div>
              <Kicker>STEP-BY-STEP ANALYSIS</Kicker>
              <div className="dr-steps" style={{ marginTop: 8 }}>
                {phases.map((phase, index) => {
                  const Icon = phase.icon;
                  const color = phaseColor(phase.state);
                  const num = String(index + 1).padStart(2, '0');
                  const extras = renderPhaseExtras(phase.id);
                  return (
                    <div key={phase.id} className="dr-step">
                      <div className="dr-step-rail">
                        <span className={`dr-step-num dr-step-num-${phase.state}`}>{num}</span>
                        {phase.state !== 'idle' && (
                          <span className={`dr-step-connector dr-step-connector-${phase.state}`} />
                        )}
                        {phase.state === 'idle' && <span className="dr-step-connector" />}
                      </div>
                      <div className={`dr-step-card dr-step-card-${phase.state}`}>
                        <div className="dr-step-head">
                          <Icon size={13} style={{ color, flexShrink: 0 }} />
                          <span className="dr-step-title">{phase.title}</span>
                          <span className={`dr-step-state dr-step-state-${phase.state}`}>
                            {phase.state === 'working' && <span className="dr-pulse" style={{ width: 6, height: 6, marginRight: 5 }} />}
                            {phaseStateLabel[phase.state]}
                          </span>
                        </div>
                        {phase.rows.length > 0 || extras ? (
                          <div className="dr-step-body">
                            {phase.rows.map(row => <PhaseRow key={row.key} row={row} />)}
                            {extras}
                          </div>
                        ) : (
                          <div className="dr-step-body">
                            <span className="dr-step-idle-text">
                              {!isDiagnosing && activeIncident?.status
                                ? 'No activity recorded for this step'
                                : index === 0
                                  ? 'Waiting for diagnosis to start…'
                                  : 'Awaiting agent activity…'}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {/* Incident history */}
        <div style={{ borderTop: '1px solid #1d1f25', paddingTop: 12, marginTop: 'auto' }}>
          <div
            onClick={() => setHistoryOpen(!historyOpen)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
          >
            <span className="dr-kicker" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <History size={11} />
              INCIDENT HISTORY ({incidentsList ? incidentsList.length : 0})
            </span>
            {historyOpen ? <ChevronUp size={13} style={{ color: 'var(--dr-faint)' }} /> : <ChevronDown size={13} style={{ color: 'var(--dr-faint)' }} />}
          </div>

          {historyOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
              {historyItems.length > 0 ? (
                historyItems.map(inc => (
                  <div key={inc.id} className="dr-file-row" style={{ border: '1px solid var(--dr-frame-soft)' }} onClick={() => onSelectIncident(inc.id)}>
                    <span>#{inc.id.slice(0, 8).toUpperCase()}</span>
                    <span style={{
                      fontWeight: 700,
                      fontSize: 10,
                      color: inc.status?.includes('VERIFIED') || inc.status?.includes('PR')
                        ? 'var(--dr-green)'
                        : inc.status?.includes('FAIL') || inc.status?.includes('CANCEL')
                          ? 'var(--dr-red)'
                          : 'var(--dr-amber)'
                    }}>
                      {inc.status}
                    </span>
                  </div>
                ))
              ) : (
                <div style={{ fontSize: 11, color: 'var(--dr-faint)' }}>No previous incidents.</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Chat-style "jump to latest" pill — appears when the agent is
          producing output while the operator is reading above the fold. */}
      {!pinned && streamLive && (
        <button type="button" className="dr-jump" onClick={jumpToLatest}>
          <ArrowDown size={12} />
          <span>New activity</span>
        </button>
      )}
    </div>
  );
}
