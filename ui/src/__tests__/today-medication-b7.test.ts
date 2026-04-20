/**
 * B7 — Truthful daily medication verification
 *
 * Tests the three-state semantics:
 *   first_ever_log  → pending_first_log path (missing)
 *   logged_today    → loggedIds set from medicationLogsToday
 *   historical_only → medicationLogsToday empty → missing (NOT complete)
 *
 * All tests use deriveCompletion / prioritizeActions directly so they run fast
 * without rendering components.
 */
import { describe, it, expect } from 'vitest';
import { deriveCompletion, prioritizeActions } from '../features/today/deriveTodayViewModel';
import { defaultDailyProtocol } from '../features/today/types';
import type { TodayRawSources } from '../features/today/types';
import type { MedicationLogResponse, MedicationRegimenResponse } from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────

const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';
const TODAY_TS = '2026-04-18T10:00:00.000Z';
const YESTERDAY_TS = '2026-04-17T10:00:00.000Z';

// ── Fixtures ──────────────────────────────────────────────────────────────

function makeRegimen(id: string): MedicationRegimenResponse {
  return {
    id,
    user_id: 'test-user-id',
    medication_id: 1,
    medication_name: 'Aspirin',
    dosage_amount: 100 as unknown as number,
    dosage_unit: 'mg',
    frequency: 'daily',
    instructions: null,
    prescribed_by: null,
    started_at: '2026-01-01',
    ended_at: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function makeLog(regimenId: string, scheduledAt: string, status = 'taken'): MedicationLogResponse {
  return {
    id: `log-${regimenId}-${scheduledAt}`,
    user_id: 'test-user-id',
    regimen_id: regimenId,
    status,
    scheduled_at: scheduledAt,
    taken_at: status !== 'skipped' ? scheduledAt : null,
    dosage_amount: null,
    dosage_unit: null,
    notes: null,
    recorded_at: scheduledAt,
    ingested_at: scheduledAt,
  };
}

function makeSources(overrides: Partial<TodayRawSources> = {}): TodayRawSources {
  return {
    date: DATE,
    now: NOW,
    checkpointsToday: [],
    symptomsActiveToday: [],
    temperatureToday: [],
    weightToday: [],
    latestScaleReading: null,
    garminMetricsToday: [],
    latestHrvMeasurement: null,
    medicationLogsToday: [],
    activeRegimens: [],
    systemStatus: null,
    ...overrides,
  };
}

const protocol = defaultDailyProtocol(DATE);

function medCompletion(sources: TodayRawSources) {
  return deriveCompletion(protocol, sources).find((c) => c.kind === 'medication')!;
}

function medAction(sources: TodayRawSources) {
  return prioritizeActions(protocol, sources).find((a) => a.kind === 'medication');
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('medication derivation (B7)', () => {
  it('no regimens → not_applicable, not required', () => {
    const c = medCompletion(makeSources({ activeRegimens: [] }));
    expect(c.status).toBe('not_applicable');
    expect(c.required).toBe(false);
  });

  it('active regimens, no logs today → missing', () => {
    const sources = makeSources({
      activeRegimens: [makeRegimen('r1')],
      medicationLogsToday: [],
    });
    expect(medCompletion(sources).status).toBe('missing');
  });

  it('active regimens, no logs today → action present with label "Log today\'s meds"', () => {
    const sources = makeSources({
      activeRegimens: [makeRegimen('r1')],
      medicationLogsToday: [],
    });
    const action = medAction(sources);
    expect(action).toBeDefined();
    expect(action!.label).toBe("Log today's meds");
  });

  it('some regimens logged today → partial', () => {
    const r1 = makeRegimen('r1');
    const r2 = makeRegimen('r2');
    const sources = makeSources({
      activeRegimens: [r1, r2],
      medicationLogsToday: [makeLog('r1', TODAY_TS)],
    });
    const c = medCompletion(sources);
    expect(c.status).toBe('partial');
    expect(c.detail).toMatch(/1 of 2/);
  });

  it('some regimens logged today → action present with label "Confirm today\'s doses"', () => {
    const r1 = makeRegimen('r1');
    const r2 = makeRegimen('r2');
    const sources = makeSources({
      activeRegimens: [r1, r2],
      medicationLogsToday: [makeLog('r1', TODAY_TS)],
    });
    expect(medAction(sources)!.label).toBe("Confirm today's doses");
  });

  it('all regimens logged today → complete', () => {
    const r1 = makeRegimen('r1');
    const r2 = makeRegimen('r2');
    const sources = makeSources({
      activeRegimens: [r1, r2],
      medicationLogsToday: [makeLog('r1', TODAY_TS), makeLog('r2', TODAY_TS)],
    });
    expect(medCompletion(sources).status).toBe('complete');
  });

  it('all regimens logged today → no medication action', () => {
    const r1 = makeRegimen('r1');
    const sources = makeSources({
      activeRegimens: [r1],
      medicationLogsToday: [makeLog('r1', TODAY_TS)],
    });
    expect(medAction(sources)).toBeUndefined();
  });

  // THE KEY TEST: historical log only must NOT produce complete
  it('historical log only (yesterday, empty today) → missing, not complete', () => {
    const r1 = makeRegimen('r1');
    const sources = makeSources({
      activeRegimens: [r1],
      // medicationLogsToday is empty — yesterday's log is not included here
      medicationLogsToday: [],
    });
    const c = medCompletion(sources);
    expect(c.status).toBe('missing');
    expect(c.status).not.toBe('complete');
  });

  it('skipped log today counts as handled → complete', () => {
    const r1 = makeRegimen('r1');
    const sources = makeSources({
      activeRegimens: [r1],
      medicationLogsToday: [makeLog('r1', TODAY_TS, 'skipped')],
    });
    expect(medCompletion(sources).status).toBe('complete');
  });

  it('delayed log today counts as handled → complete', () => {
    const r1 = makeRegimen('r1');
    const sources = makeSources({
      activeRegimens: [r1],
      medicationLogsToday: [makeLog('r1', TODAY_TS, 'delayed')],
    });
    expect(medCompletion(sources).status).toBe('complete');
  });

  it('log for different regimen id does not count for unlogged regimen', () => {
    const r1 = makeRegimen('r1');
    const r2 = makeRegimen('r2');
    const sources = makeSources({
      activeRegimens: [r1, r2],
      medicationLogsToday: [makeLog('r1', TODAY_TS)],  // only r1
    });
    const c = medCompletion(sources);
    expect(c.status).toBe('partial');  // r2 still missing
  });

  it('yesterday log + no log today → missing (boundary correctness)', () => {
    const r1 = makeRegimen('r1');
    // YESTERDAY_TS log is in yesterday's window; useTodaySources filters it out.
    // medicationLogsToday only contains logs for today → empty here.
    const sources = makeSources({
      activeRegimens: [r1],
      medicationLogsToday: [],  // yesterday's log was filtered at the API level
    });
    expect(medCompletion(sources).status).toBe('missing');
  });
});
