import { useEffect, useMemo, useRef, useState } from 'react';
import { buildStages, runningCopy } from './diagnosisTimeline';

// Presentation pacing for the live diagnosis timeline. Backend events are real
// but frequently arrive as a burst (the first few operations complete in
// milliseconds and the SSE stream replays any activity recorded before the
// browser subscribed). Revealing them one at a time lets a viewer actually
// watch each operation happen instead of seeing a wall of pre-completed steps.
//
// This never invents progress: it only ever displays events the backend has
// already emitted. It merely paces how fast a *completed* event is visually
// settled (a short "in progress" beat, then the checkmark) and how quickly the
// next event is shown. The pacing clock is independent of event arrival time,
// so a burst of replayed events cannot fast-forward the reveal.
// The backend often completes the early investigation steps in a few
// milliseconds and then replays them to a newly-subscribed browser in a burst.
// Revealing them instantly would make a diagnosis look scripted ("demo data").
// Instead each step is deliberately paced so a viewer can follow it: appear →
// work ("in progress") beat → settle with a tick → pause → next step.
const STEP_RUN_MS = 1650; // how long a finished step shows its in-progress beat
const STEP_GAP_MS = 620; // pause between settling a step and revealing the next
const RUN_POLL_MS = 260; // poll interval while a step is genuinely in flight
const SETTLED_POLL_MS = 650; // poll interval after the whole flow has settled
const TICK_MS = 150; // base scheduler tick

const TERMINAL = new Set(['done', 'failed', 'cancelled', 'skipped']);

function lastRowMessage(stage) {
  return [...(stage.rows || [])].reverse().find((row) => row.message)?.message || '';
}

/**
 * @param {Array} rawEvents — the raw SSE/activity event list for the active run.
 * @returns {Array} progressively revealed stage objects. Each stage carries a
 *   `phase` of 'buffering' (visible, still "working") or 'settled' (showing its
 *   real status), plus the real stage fields from buildStages.
 */
export function useProgressiveTimeline(rawEvents = []) {
  const target = useMemo(() => buildStages(rawEvents), [rawEvents]);
  const [visible, setVisible] = useState([]);

  const targetRef = useRef(target);
  const visibleRef = useRef(visible);
  targetRef.current = target;
  visibleRef.current = visible;

  useEffect(() => {
    let deadline = 0; // timestamp (ms) before which no action is taken

    const commit = (next) => {
      visibleRef.current = next;
      setVisible(next);
    };

    const advance = () => {
      const now = Date.now();
      if (now < deadline) return;

      const target = targetRef.current;
      const current = visibleRef.current;

      // A fresh (or cleared) run: drop everything.
      if (!target.length) {
        if (current.length) commit([]);
        deadline = 0;
        return;
      }

      // Reconcile already-settled rows with newer statuses/messages (most
      // importantly WAITING → done after an approval). A status transition is
      // committed on its own beat; the next operation must not appear in the
      // same paint as the approval tick.
      let reconciled = false;
      let statusChanged = false;
      const base = current.map((row) => {
        if (row.phase !== 'settled') return row;
        const targetRow = target.find((r) => r.key === row.key);
        if (!targetRow) return row;
        const messageChanged = lastRowMessage(targetRow) !== lastRowMessage(row);
        if (targetRow.status !== row.status || messageChanged) {
          reconciled = true;
          statusChanged ||= targetRow.status !== row.status;
          return { ...targetRow, phase: 'settled' };
        }
        return row;
      });

      if (statusChanged) {
        commit(base);
        deadline = now + STEP_GAP_MS;
        return;
      }

      // 1. Settle the buffering row once the backend reports a terminal status.
      const bufferingIndex = base.findIndex((r) => r.phase === 'buffering');
      if (bufferingIndex !== -1) {
        const key = base[bufferingIndex].key;
        const targetRow = target.find((r) => r.key === key);
        const next = base.slice();
        if (!targetRow) {
          next.splice(bufferingIndex, 1);
          commit(next);
          deadline = now;
          return;
        }
        if (TERMINAL.has(targetRow.status)) {
          next[bufferingIndex] = { ...targetRow, phase: 'settled' };
          commit(next);
          deadline = now + STEP_GAP_MS;
        } else {
          // Genuinely in flight — show the real progress text, keep buffering.
          next[bufferingIndex] = { ...targetRow, phase: 'buffering' };
          commit(next);
          deadline = now + RUN_POLL_MS;
        }
        return;
      }

      // 2. Reveal the next stage. Waiting/failed stages surface immediately
      // (there is nothing to "buffer" — the user must act); every other stage
      // appears with a short in-progress beat before it ticks over.
      const visibleKeys = new Set(base.map((row) => row.key));
      const targetRow = target.find((row) => !visibleKeys.has(row.key));
      if (targetRow) {
        const instant = targetRow.status === 'waiting' || targetRow.status === 'failed';
        const revealed = instant
          ? { ...targetRow, phase: 'settled' }
          : {
              ...targetRow,
              phase: 'buffering',
              displayMessage: runningCopy(targetRow.id),
            };
        commit([...base, revealed]);
        deadline = now + (instant ? STEP_GAP_MS : STEP_RUN_MS);
        return;
      }

      // 3. Everything is revealed — persist any reconciliation and keep
      // watching for late status changes.
      if (reconciled) commit(base);
      deadline = now + SETTLED_POLL_MS;
    };

    const id = setInterval(advance, TICK_MS);
    return () => clearInterval(id);
  }, []);

  return visible;
}
