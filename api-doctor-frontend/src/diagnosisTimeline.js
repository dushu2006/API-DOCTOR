// Shared diagnosis timeline model.
//
// Turns the raw backend event stream (SSE / replayed activity) into a small,
// ordered set of investigation stages. This is the single source of truth for
// stage order, labels and running-copy — both the progressive revealer
// (useProgressiveTimeline) and the API Doctor panel read from it, so the
// timeline can never drift out of sync with the backend's real events.

export const REPEATING_STEPS = new Set(['file_read']);

// Steps whose `pending` status means "waiting for the developer" rather than
// "waiting for the machine". Only these can put a stage into the WAITING state.
const APPROVAL_STEPS = new Set(['file_read_approval', 'fix_approval']);

// Umbrella steps that never get their own timeline row. `collecting_context`
// is the backend's internal umbrella for "parse trace → identify files → read
// files", which is already surfaced by STACK TRACE ANALYSIS, SOURCE ACCESS and
// SOURCE READING.
const IGNORED_STEPS = new Set(['collecting_context', 'pipeline', 'reset']);

// Ordered investigation stages. Each maps the raw step names it is composed
// of. Steps that never occur are simply absent from the rendered timeline, so
// a diagnosis that skips a phase (e.g. no logs available) never shows a fake
// "completed" row for it.
export const STAGES = [
  { id: 'error', label: 'ERROR DETECTION', steps: ['error_detected'] },
  { id: 'logs', label: 'LOG RETRIEVAL', steps: ['logs_retrieved'] },
  { id: 'trace', label: 'STACK TRACE ANALYSIS', steps: ['stack_trace_parsed'] },
  {
    id: 'repo',
    label: 'REPOSITORY DISCOVERY',
    steps: ['repository_check', 'repository_connected', 'repository_verified', 'repository_synced', 'repository_synchronized', 'project_discovered'],
  },
  {
    id: 'access',
    label: 'SOURCE ACCESS',
    steps: ['relevant_source_identified', 'files_to_read', 'file_read_approval'],
  },
  { id: 'read', label: 'SOURCE READING', steps: ['file_read'] },
  { id: 'investigate', label: 'ROOT CAUSE INVESTIGATION', steps: ['investigating', 'investigation_started'] },
  { id: 'cause', label: 'ROOT CAUSE IDENTIFICATION', steps: ['root_cause_identified'] },
  { id: 'fix', label: 'REPAIR GENERATION', steps: ['fix_generated', 'fix_regenerating'] },
  { id: 'review', label: 'FIX REVIEW', steps: ['fix_approval', 'diff_ready'] },
  { id: 'apply', label: 'PATCH APPLICATION', steps: ['changes_applied'] },
  {
    id: 'sandbox',
    label: 'SANDBOX VERIFICATION',
    steps: ['sandbox_started', 'reproduce_failure', 'apply_patch', 'run_tests', 'run_build', 'health_check', 'verify_fix', 'tests_started', 'test_passed'],
  },
  { id: 'verify', label: 'VERIFICATION', steps: ['fix_verified', 'workspace_updated', 'changes_rolled_back'] },
  { id: 'delivery', label: 'DELIVERY', steps: ['local_commit', 'branch_created', 'commit_created', 'pr_created', 'human_review'] },
];

// Fallback labels for steps (used only when a step is not part of STAGES).
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

// The "in progress" copy shown while a stage is buffering. For a stage that
// has genuinely finished this is a short presentation beat; for a stage the
// backend is still working on it is replaced by the real message.
const RUNNING_COPY = {
  error: 'Detecting API failure…',
  logs: 'Retrieving runtime logs…',
  trace: 'Parsing exception frames…',
  repo: 'Connecting to repository…',
  access: 'Mapping failure to source…',
  read: 'Reading source files…',
  context: 'Assembling investigation context…',
  investigate: 'Tracing execution path…',
  cause: 'Identifying root cause…',
  fix: 'Generating minimal repair…',
  review: 'Preparing patch for review…',
  apply: 'Applying patch to workspace…',
  sandbox: 'Running sandbox verification…',
  verify: 'Verifying the repair…',
  delivery: 'Preparing delivery…',
};

export function runningCopy(stageId) {
  return RUNNING_COPY[stageId] || 'Working…';
}

// Pull the per-file target out of a "Reading app/x.py" / "Read app/x.py · N lines" message.
export function normalizedTarget(message = '') {
  return message.replace(/^(Reading|Read)\s+/, '').split(' · ')[0].trim();
}

// Collapse the raw event stream into a flat, deduplicated list of rows. A
// running event and its matching done event become one row that carries the
// latest status/message.
export function buildTimeline(events = []) {
  const rows = [];
  const byKey = new Map();
  for (const event of events) {
    if (!event) continue;
    if (event.type === 'connected' || IGNORED_STEPS.has(event.step)) continue;
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

// Group the flat timeline into ordered investigation stages.
export function buildStages(events = []) {
  const rows = buildTimeline(events);
  const rowsByStep = new Map();
  for (const row of rows) {
    if (!rowsByStep.has(row.step)) rowsByStep.set(row.step, []);
    rowsByStep.get(row.step).push(row);
  }

  const stages = [];
  const covered = new Set();
  for (const stage of STAGES) {
    const memberRows = stage.steps.flatMap((step) => rowsByStep.get(step) || []);
    if (!memberRows.length) continue;
    memberRows.forEach((r) => covered.add(r.step));
    stages.push({ ...stage, rows: memberRows, status: stageStatus(memberRows) });
  }

  // Any step not modelled by STAGES still gets surfaced as its own stage so
  // the timeline never silently drops a real backend event.
  for (const row of rows) {
    if (covered.has(row.step)) continue;
    covered.add(row.step);
    stages.push({
      id: row.step,
      label: STEP_LABELS[row.step] || row.step.replace(/_/g, ' ').toUpperCase(),
      steps: [row.step],
      rows: [row],
      status: stageStatus([row]),
    });
  }
  return stages;
}
