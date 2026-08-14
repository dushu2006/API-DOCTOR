// Shared diagnosis timeline model.
//
// Raw SSE events can arrive in a burst even though they describe separate real
// operations. This module turns that stream into stable, individually
// inspectable steps. The presentation layer may pace those steps, but it never
// invents an operation or a result.

export const REPEATING_STEPS = new Set(['file_read']);

const APPROVAL_STEPS = new Set(['file_read_approval', 'fix_approval']);
const IGNORED_STEPS = new Set(['collecting_context', 'pipeline', 'reset']);

// Keep stages deliberately small. Repository checks, project discovery and
// source approval used to be collapsed into one large card, making several
// operations appear to finish at once. Each meaningful operation now gets its
// own row and explanation.
export const STAGES = [
  { id: 'error', label: 'ERROR DETECTION', steps: ['error_detected'] },
  { id: 'logs', label: 'LOG RETRIEVAL', steps: ['logs_retrieved'] },
  { id: 'repo', label: 'REPOSITORY VERIFICATION', steps: ['repository_check', 'repository_connected', 'repository_verified'] },
  { id: 'sync', label: 'WORKSPACE STATE', steps: ['repository_synced', 'repository_synchronized'] },
  { id: 'project', label: 'PROJECT DISCOVERY', steps: ['project_discovered'] },
  { id: 'trace', label: 'STACK TRACE ANALYSIS', steps: ['stack_trace_parsed'] },
  { id: 'source', label: 'SOURCE MAPPING', steps: ['relevant_source_identified', 'files_to_read'] },
  { id: 'access', label: 'SOURCE ACCESS APPROVAL', steps: ['file_read_approval'] },
  // file_read is expanded into one stage per real file below.
  { id: 'investigate', label: 'ROOT CAUSE INVESTIGATION', steps: ['investigating', 'investigation_started'] },
  { id: 'cause', label: 'ROOT CAUSE IDENTIFICATION', steps: ['root_cause_identified'] },
  { id: 'fix', label: 'REPAIR GENERATION', steps: ['fix_generated', 'fix_regenerating'] },
  { id: 'review', label: 'FIX REVIEW', steps: ['fix_approval', 'diff_ready'] },
  { id: 'apply', label: 'PATCH APPLICATION', steps: ['changes_applied'] },
  { id: 'sandbox', label: 'SANDBOX VERIFICATION', steps: ['sandbox_started', 'reproduce_failure', 'apply_patch', 'run_tests', 'run_build', 'health_check', 'verify_fix', 'tests_started', 'test_passed'] },
  { id: 'verify', label: 'VERIFICATION', steps: ['fix_verified', 'workspace_updated', 'changes_rolled_back'] },
  { id: 'delivery', label: 'DELIVERY', steps: ['local_commit', 'branch_created', 'commit_created', 'pr_created', 'human_review'] },
];

export const STEP_LABELS = {
  error_detected: 'ERROR DETECTION',
  logs_retrieved: 'LOG RETRIEVAL',
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

const RUNNING_COPY = {
  error: 'Detecting API failure…',
  logs: 'Retrieving runtime logs…',
  repo: 'Verifying the repository workspace…',
  sync: 'Checking branch and workspace state…',
  project: 'Detecting language and framework…',
  trace: 'Parsing exception frames…',
  source: 'Mapping the failure to relevant source…',
  access: 'Preparing the source access request…',
  read: 'Reading the approved source file…',
  investigate: 'Tracing the execution path…',
  cause: 'Identifying root cause…',
  fix: 'Generating a minimal repair…',
  review: 'Preparing the patch for review…',
  apply: 'Applying the patch to the workspace…',
  sandbox: 'Running sandbox verification…',
  verify: 'Verifying the repair…',
  delivery: 'Preparing delivery…',
};

export function runningCopy(stageId) {
  return RUNNING_COPY[stageId] || 'Working…';
}

export function normalizedTarget(message = '') {
  return message.replace(/^(Reading|Read)\s+/, '').split(' · ')[0].trim();
}

// A running event and its matching terminal event become one row carrying the
// latest real status/message. File reads are keyed by path because they repeat.
export function buildTimeline(events = []) {
  const rows = [];
  const byKey = new Map();
  for (const event of events) {
    if (!event || event.type === 'connected' || IGNORED_STEPS.has(event.step)) continue;
    const step = event.step || '';
    const message = event.message || '';
    if (!step && !message) continue;
    const key = REPEATING_STEPS.has(step) ? `${step}:${normalizedTarget(message)}` : step || message;
    const row = {
      key,
      step,
      label: STEP_LABELS[step] || step.replace(/_/g, ' ').toUpperCase(),
      message,
      status: event.status || 'running',
      ts: event.ts || event.timestamp || null,
    };
    const existingIndex = byKey.get(key);
    if (existingIndex === undefined) {
      byKey.set(key, rows.length);
      rows.push(row);
    } else {
      rows[existingIndex] = { ...rows[existingIndex], ...row };
    }
  }
  return rows;
}

function stageStatus(rows) {
  if (rows.some((r) => r.status === 'failed' || r.status === 'cancelled')) return 'failed';
  if (rows.some((r) => APPROVAL_STEPS.has(r.step) && r.status === 'pending')) return 'waiting';
  if (rows.some((r) => r.status === 'running')) return 'running';
  return 'done';
}

export function buildStages(events = []) {
  const rows = buildTimeline(events);
  const rowsByStep = new Map();
  for (const row of rows) {
    if (!rowsByStep.has(row.step)) rowsByStep.set(row.step, []);
    rowsByStep.get(row.step).push(row);
  }

  const stages = [];
  const coveredKeys = new Set();
  for (const definition of STAGES) {
    const memberRows = definition.steps.flatMap((step) => rowsByStep.get(step) || []);
    if (!memberRows.length) continue;
    memberRows.forEach((row) => coveredKeys.add(row.key));
    stages.push({
      ...definition,
      key: `stage:${definition.id}`,
      rows: memberRows,
      status: stageStatus(memberRows),
    });

    // Put each approved file read on the timeline as its own clickable step.
    // It is inserted immediately after SOURCE ACCESS, before investigation.
    if (definition.id === 'access') {
      for (const row of rowsByStep.get('file_read') || []) {
        coveredKeys.add(row.key);
        const target = normalizedTarget(row.message);
        stages.push({
          id: 'read',
          key: row.key,
          label: target ? `READING ${target.split('/').pop()}` : 'READING SOURCE',
          steps: ['file_read'],
          rows: [row],
          status: stageStatus([row]),
        });
      }
    }
  }

  // A run with no approval event can still have file reads (for compatibility
  // with older backend activity). Place those before investigation.
  const orphanReads = (rowsByStep.get('file_read') || []).filter((row) => !coveredKeys.has(row.key));
  if (orphanReads.length) {
    const insertAt = Math.max(0, stages.findIndex((stage) => stage.id === 'investigate'));
    const readStages = orphanReads.map((row) => ({
      id: 'read',
      key: row.key,
      label: `READING ${normalizedTarget(row.message).split('/').pop() || 'SOURCE'}`,
      steps: ['file_read'],
      rows: [row],
      status: stageStatus([row]),
    }));
    readStages.forEach((stage) => stage.rows.forEach((row) => coveredKeys.add(row.key)));
    stages.splice(insertAt, 0, ...readStages);
  }

  // Never silently drop an unmodelled real backend event.
  for (const row of rows) {
    if (coveredKeys.has(row.key)) continue;
    coveredKeys.add(row.key);
    stages.push({
      id: row.step,
      key: `event:${row.key}`,
      label: STEP_LABELS[row.step] || row.step.replace(/_/g, ' ').toUpperCase(),
      steps: [row.step],
      rows: [row],
      status: stageStatus([row]),
    });
  }
  return stages;
}
