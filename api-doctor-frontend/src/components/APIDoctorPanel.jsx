import React, { useEffect, useMemo, useRef } from 'react';
import {
  Activity,
  Check,
  FileCode2,
  Flag,
  GitCommit,
  GitPullRequest,
  MoreVertical,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react';
import './doctor.css';

const STEP_LABELS = {
  error_detected: 'ERROR DETECTION',
  logs_retrieved: 'LOGS RETRIEVED',
  repository_check: 'CHECKING WORKSPACE',
  repository_connected: 'WORKSPACE CONNECTED',
  repository_verified: 'REPOSITORY VERIFIED',
  repository_synced: 'WORKSPACE STATE CHECKED',
  repository_synchronized: 'PROJECT SYNCHRONIZED',
  project_discovered: 'PROJECT DISCOVERED',
  stack_trace_parsed: 'STACK TRACE PARSED',
  relevant_source_identified: 'RELEVANT SOURCE IDENTIFIED',
  files_to_read: 'SOURCE FILES QUEUED',
  file_read_approval: 'SOURCE ACCESS APPROVAL',
  file_read: 'READING SOURCE',
  collecting_context: 'BUILDING CONTEXT',
  investigating: 'INVESTIGATING ROOT CAUSE',
  investigation_started: 'INVESTIGATING ROOT CAUSE',
  root_cause_identified: 'ROOT CAUSE IDENTIFIED',
  fix_generated: 'GENERATING FIX',
  fix_regenerating: 'REGENERATING FIX',
  fix_approval: 'FIX READY FOR REVIEW',
  diff_ready: 'PATCH PREPARED',
  changes_applied: 'CHANGES APPLIED',
  sandbox_started: 'SANDBOX VERIFICATION',
  tests_started: 'RUNNING TESTS',
  reproduce_failure: 'FAILURE REPRODUCED',
  apply_patch: 'PATCH APPLIED IN SANDBOX',
  run_tests: 'TEST SUITE EXECUTED',
  run_build: 'BUILD CHECKED',
  health_check: 'HEALTH CHECKED',
  verify_fix: 'FIX BEHAVIOUR VERIFIED',
  test_passed: 'TESTS PASSED',
  fix_verified: 'FIX VERIFIED',
  changes_rolled_back: 'CHANGES ROLLED BACK',
  workspace_updated: 'WORKSPACE UPDATED',
  local_commit: 'LOCAL COMMIT CREATED',
  branch_created: 'REPAIR BRANCH CREATED',
  commit_created: 'COMMIT CREATED',
  pr_created: 'PULL REQUEST CREATED',
  human_review: 'HUMAN REVIEW',
  pipeline_error: 'PIPELINE ERROR',
  fresh_start: 'FRESH DIAGNOSIS STARTED',
};

const FLOW = [
  { id: 'error', label: 'ERROR DETECTION', steps: ['error_detected'] },
  { id: 'logs', label: 'LOGS RETRIEVED', steps: ['logs_retrieved'] },
  { id: 'workspace', label: 'WORKSPACE CONNECTED', steps: ['repository_check', 'repository_connected', 'repository_verified', 'repository_synced', 'repository_synchronized', 'project_discovered'] },
  { id: 'trace', label: 'STACK TRACE PARSED', steps: ['stack_trace_parsed'] },
  { id: 'source', label: 'RELEVANT SOURCE IDENTIFIED', steps: ['collecting_context', 'relevant_source_identified', 'files_to_read', 'file_read_approval'] },
  { id: 'read', label: 'READING SOURCE', steps: ['file_read'] },
  { id: 'root', label: 'INVESTIGATING ROOT CAUSE', steps: ['investigating', 'investigation_started'] },
  { id: 'cause', label: 'ROOT CAUSE IDENTIFIED', steps: ['root_cause_identified'] },
  { id: 'fix', label: 'GENERATING FIX', steps: ['fix_generated', 'fix_regenerating'] },
  { id: 'review', label: 'FIX READY FOR REVIEW', steps: ['fix_approval', 'diff_ready'] },
  { id: 'sandbox', label: 'SANDBOX VERIFICATION', steps: ['changes_applied', 'sandbox_started', 'reproduce_failure', 'apply_patch'] },
  { id: 'tests', label: 'RUNNING TESTS', steps: ['tests_started', 'run_tests', 'run_build', 'health_check', 'verify_fix', 'test_passed'] },
  { id: 'verified', label: 'FIX VERIFIED', steps: ['fix_verified', 'workspace_updated', 'changes_rolled_back'] },
  { id: 'delivery', label: 'DELIVERY READY', steps: ['local_commit', 'branch_created', 'commit_created', 'pr_created', 'human_review'] },
];

const REPEATING_STEPS = new Set(['file_read']);

function normalizedTarget(message = '') {
  return message.replace(/^(Reading|Read)\s+/, '').split(' · ')[0].trim();
}

/** Merge running/done SSE pairs while preserving the real event sequence. */
function buildTimeline(events = []) {
  const rows = [];
  const byKey = new Map();
  for (const event of events) {
    if (!event || event.type === 'connected' || event.step === 'pipeline' || event.step === 'reset') continue;
    const step = event.step || '';
    const message = event.message || '';
    if (!step && !message) continue;
    const key = REPEATING_STEPS.has(step) ? `${step}:${normalizedTarget(message)}` : step || message;
    const existing = byKey.get(key);
    const row = {
      key,
      step,
      label: STEP_LABELS[step] || step.replace(/_/g, ' ').toUpperCase(),
      message,
      status: event.status || 'running',
    };
    if (existing === undefined) {
      byKey.set(key, rows.length);
      rows.push(row);
    } else {
      rows[existing] = { ...rows[existing], ...row };
    }
  }
  return rows;
}

function stageState(events) {
  if (!events.length) return 'idle';
  if (events.some(event => event.status === 'failed' || event.status === 'cancelled')) return 'failed';
  if (events.some(event => ['running', 'pending', 'paused'].includes(event.status))) return 'running';
  return 'done';
}

function StepIcon({ state }) {
  if (state === 'done') return <span className="live-step-icon is-done"><Check size={11} strokeWidth={2.5} /></span>;
  if (state === 'running') return <span className="live-step-icon is-running"><Search size={10} /></span>;
  if (state === 'failed') return <span className="live-step-icon is-failed"><X size={11} /></span>;
  return <span className="live-step-icon is-idle"><Flag size={9} /></span>;
}

export default function APIDoctorPanel({
  activeRun,
  runContext,
  runDiff,
  runSandbox,
  runPR,
  timelineEvents = [],
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
  doctorWidth = 300,
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
  const timelineRows = useMemo(() => buildTimeline(timelineEvents), [timelineEvents]);
  const stages = useMemo(() => FLOW.map(stage => {
    const rows = timelineRows.filter(row => stage.steps.includes(row.step));
    return { ...stage, rows, state: stageState(rows) };
  }), [timelineRows]);

  const lastStarted = stages.reduce((latest, stage, index) => stage.state !== 'idle' ? index : latest, -1);
  const visibleStages = stages.slice(0, Math.min(stages.length, Math.max(1, lastStarted + 2)));
  const targetFile = runContext?.implicated_files?.[0]
    || activeRun?.root_cause?.affected_files?.[0]
    || selectedFile
    || 'workspace';
  const isAwaitingRead = activeRun?.status === 'AWAITING_FILE_READ_APPROVAL';
  const isAwaitingFix = activeRun?.status === 'AWAITING_FIX_APPROVAL';
  const failed = Boolean(runSandbox?.present && runSandbox.passed === false)
    || activeRun?.status?.includes('FAIL');
  const verified = Boolean(runSandbox?.passed) || activeRun?.status === 'FIX_VERIFIED';

  useEffect(() => {
    if (!bodyRef.current || !activeRun) return;
    bodyRef.current.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' });
  }, [timelineRows.length, activeRun]);

  if (!isDoctorOpen) return null;

  return (
    <aside className="doctor-panel" style={{ width: `${doctorWidth}px` }}>
      <div className="doctor-panel-header">
        <span><ShieldCheck size={13} /> {activeRun ? 'LIVE INVESTIGATION' : 'DOCTOR PANEL'}</span>
        <div>
          {activeRun && <button type="button" title="Fresh start" onClick={onNewDiagnosis}><RefreshCw size={11} /></button>}
          <button type="button" title="Close panel" onClick={() => setIsDoctorOpen(false)}><MoreVertical size={13} /></button>
        </div>
      </div>

      {!activeRun ? (
        <div className="doctor-idle">
          <div className="doctor-idle-main">
            <div className="doctor-idle-icon"><Activity size={34} /></div>
            <h2>READY FOR DIAGNOSIS</h2>
            <p>Workspace loaded. API Doctor is standing by to scan your project for structural issues and runtime failures.</p>
            <button type="button" className="doctor-start" onClick={onStartDiagnosis}>
              <Play size={13} fill="currentColor" /> START DIAGNOSIS
            </button>
            <button type="button" className="doctor-manual" onClick={onOpenIngestModal}>PASTE ERROR / STACK TRACE</button>
            {demoMode && onRunDemoScenario && (
              <button type="button" className="doctor-manual" disabled={isDemoPending} onClick={() => onRunDemoScenario('external_api')}>
                {isDemoPending ? 'STARTING DEMO…' : 'RUN DEMO DIAGNOSIS'}
              </button>
            )}
          </div>
          <div className="doctor-context">
            <div className="doctor-context-title">CURRENT CONTEXT</div>
            <div><span>Target</span><strong>{targetFile}</strong></div>
            <div><span>Framework</span><strong>{projectProfile?.framework || projectProfile?.language || 'AUTO-DETECTED'}</strong></div>
            <div><span>Ruleset</span><strong className="is-purple">STRICT + SECURITY</strong></div>
          </div>
        </div>
      ) : (
        <div className="doctor-live" ref={bodyRef}>
          <div className="live-steps">
            {visibleStages.map((stage, index) => {
              const latest = stage.rows[stage.rows.length - 1];
              const detail = latest?.message && latest.message !== stage.label ? latest.message : '';
              return (
                <div className={`live-step is-${stage.state}`} key={stage.id}>
                  <div className="live-step-rail">
                    <StepIcon state={stage.state} />
                    {index < visibleStages.length - 1 && <span className="live-step-line" />}
                  </div>
                  <div className="live-step-copy">
                    <strong>{latest?.label || stage.label}</strong>
                    <small>{detail || (stage.state === 'idle' ? 'Waiting...' : stage.state === 'running' ? 'Analysis in progress...' : 'Completed')}</small>
                    {stage.id === 'source' && isAwaitingRead && (
                      <div className="doctor-inline-actions">
                        <button type="button" disabled={isRunActionPending} onClick={() => onApproveFileRead(true)}>ALLOW</button>
                        <button type="button" disabled={isRunActionPending} onClick={() => onApproveFileRead(false)}>DENY</button>
                      </div>
                    )}
                    {stage.id === 'read' && stage.rows.length > 1 && (
                      <small>{stage.rows.length} source files processed</small>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {activeRun.root_cause && (
            <div className="doctor-result-card">
              <span>ROOT CAUSE</span>
              <strong>{activeRun.root_cause.classification || activeRun.root_cause.category || 'CODE ISSUE'}</strong>
              <p>{activeRun.root_cause.reason || activeRun.root_cause.root_cause}</p>
            </div>
          )}

          {runDiff?.present && isAwaitingFix && (
            <div className="doctor-action-card">
              <span>PATCH READY</span>
              <strong>{runDiff.summary || 'Proposed repair'}</strong>
              <button type="button" onClick={() => setIsDiffMode(true)}>REVIEW DIFF</button>
              <div>
                <button type="button" className="is-primary" disabled={isRunActionPending} onClick={onKeepChanges}>KEEP CHANGES</button>
                <button type="button" disabled={isRunActionPending} onClick={onRejectChanges}>REJECT</button>
              </div>
            </div>
          )}

          {failed && (
            <div className="doctor-action-card is-failed">
              <span>VERIFICATION FAILED</span>
              <p>{runSandbox?.error || activeRun.error_message || 'The proposed change did not pass verification.'}</p>
              <button type="button" disabled={isRunActionPending} onClick={onRestart}><RotateCcw size={11} /> RUN FRESH DIAGNOSIS</button>
              {runDiff?.present && <button type="button" onClick={() => setIsDiffMode(true)}>REVIEW CURRENT DIFF</button>}
            </div>
          )}

          {verified && (
            <div className="doctor-action-card is-success">
              <span>FIX VERIFIED</span>
              <strong>{runDiff?.summary || 'All checks passed'}</strong>
              {runDiff?.present && !runDiff.applied && <button type="button" onClick={onApplyFix}>APPLY TO WORKSPACE</button>}
              {!activeRun.commit_sha && <button type="button" onClick={onCommitChanges}><GitCommit size={11} /> COMMIT CHANGES</button>}
              {!runPR?.present && <button type="button" className="is-primary" onClick={onCreatePR}><GitPullRequest size={11} /> CREATE PULL REQUEST</button>}
              {runPR?.present && <a href={runPR.pr_url} target="_blank" rel="noreferrer">OPEN PULL REQUEST ↗</a>}
            </div>
          )}

          <div className="doctor-live-context">
            <span>{targetFile}</span>
            <button type="button" onClick={() => setSelectedFile(targetFile)}><FileCode2 size={11} /> OPEN FILE</button>
          </div>
        </div>
      )}
    </aside>
  );
}
