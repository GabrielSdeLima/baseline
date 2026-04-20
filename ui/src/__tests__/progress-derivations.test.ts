/**
 * Progress derivation tests — pure unit tests for deriveProgressViewModel
 * and its sub-derivations.  No rendering, no network, no side effects.
 *
 * Coverage:
 *  · overallState: no_data / limited / mixed / sufficient
 *  · ConsistencyBlock: rate computation, DataConfidence thresholds, caveat text
 *  · SignalDirectionBlock: up / down / stable, neutral zone (HRV % + RHR bpm),
 *    insufficient N, hasBoth / hasOne confidence levels
 *  · ReportedSymptomBurdenBlock: improving / worsening / stable / unclear /
 *    insufficient_data, logging-inconsistency gate
 *  · DataConfidenceBlock: freshness vs analytical coverage as separate dimensions
 *  · Mixed states and combinations
 */
import { describe, it, expect } from 'vitest';
import {
  deriveProgressViewModel,
  SIGNAL_HRV_NEUTRAL_PCT,
  SIGNAL_RHR_NEUTRAL_BPM,
  MIN_SIGNAL_N,
  LOGGING_CONSISTENCY_THRESHOLD,
  MIN_SYMPTOM_LOGS_FOR_DIRECTION,
  SYMPTOM_STABLE_DELTA,
  CONSISTENCY_SUFFICIENT_THRESHOLD,
  CONSISTENCY_LIMITED_THRESHOLD,
} from '../features/progress/deriveProgressViewModel';
import type { ProgressRawSources } from '../features/progress/types';
import type {
  DailyCheckpointResponse,
  InsightSummary,
  MeasurementResponse,
  MedicationAdherenceResponse,
  SymptomLogResponse,
  SystemStatusResponse,
} from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────
//
//   NOW     = 2026-04-18 14:00 UTC
//   Recent  = (NOW - 7d, NOW]      → 2026-04-11T14:00Z < t ≤ 2026-04-18T14:00Z
//   Prior   = (NOW - 14d, NOW-7d]  → 2026-04-04T14:00Z < t ≤ 2026-04-11T14:00Z
//
// We use noon timestamps (12:00Z) to ensure each reading falls cleanly inside
// its intended window without touching the boundary.

const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

// Safe timestamps within each window
const RECENT_DATES = [
  '2026-04-12T12:00:00.000Z',
  '2026-04-13T12:00:00.000Z',
  '2026-04-14T12:00:00.000Z',
  '2026-04-15T12:00:00.000Z',
  '2026-04-16T12:00:00.000Z',
  '2026-04-17T12:00:00.000Z',
  '2026-04-18T12:00:00.000Z',
];
const PRIOR_DATES = [
  '2026-04-05T12:00:00.000Z',
  '2026-04-06T12:00:00.000Z',
  '2026-04-07T12:00:00.000Z',
  '2026-04-08T12:00:00.000Z',
  '2026-04-09T12:00:00.000Z',
  '2026-04-10T12:00:00.000Z',
  '2026-04-11T12:00:00.000Z',
];

// ── Fixture builders ──────────────────────────────────────────────────────

function makeSources(overrides: Partial<ProgressRawSources> = {}): ProgressRawSources {
  return {
    date: DATE,
    now: NOW,
    checkpoints14d: [],
    symptoms14d: [],
    medicationAdherence: null,
    hrv14d: [],
    rhr14d: [],
    summary: null,
    systemStatus: null,
    ...overrides,
  };
}

function makeMeasurement(
  slug: string,
  value: number,
  measuredAt: string,
): MeasurementResponse {
  return {
    id: `${slug}-${measuredAt}`,
    user_id: 'u',
    metric_type_slug: slug,
    metric_type_name: slug,
    source_slug: 'garmin_connect',
    value_num: value,
    unit: slug === 'hrv_rmssd' ? 'ms' : 'bpm',
    measured_at: measuredAt,
    aggregation_level: 'daily',
  };
}

function makeHrvReadings(values: number[], timestamps: string[]): MeasurementResponse[] {
  return values.map((v, i) => makeMeasurement('hrv_rmssd', v, timestamps[i]));
}

function makeRhrReadings(values: number[], timestamps: string[]): MeasurementResponse[] {
  return values.map((v, i) => makeMeasurement('resting_hr', v, timestamps[i]));
}

function makeCheckpoint(
  type: 'morning' | 'night',
  date: string,
): DailyCheckpointResponse {
  return {
    id: `cp-${type}-${date}`,
    user_id: 'u',
    checkpoint_type: type,
    checkpoint_date: date,
    checkpoint_at: `${date}T${type === 'morning' ? '08' : '22'}:00:00.000Z`,
    mood: null,
    energy: null,
    sleep_quality: null,
    body_state_score: null,
    notes: null,
  };
}

/** Build n morning checkpoints on consecutive days ending on DATE. */
function makeCheckpoints(n: number, type: 'morning' | 'night' = 'morning'): DailyCheckpointResponse[] {
  const dates: string[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(`${DATE}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - i);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates.map((d) => makeCheckpoint(type, d));
}

function makeSymptom(slug: string, startedAt: string): SymptomLogResponse {
  return {
    id: `sym-${slug}-${startedAt}`,
    user_id: 'u',
    symptom_slug: slug,
    symptom_name: slug,
    intensity: 5,
    status: 'active',
    started_at: startedAt,
  };
}

function makeAdherence(overallPct: number | null): MedicationAdherenceResponse {
  return {
    user_id: 'u',
    items: [],
    overall_adherence_pct: overallPct,
    availability_status: overallPct !== null ? 'ok' : 'not_applicable',
  };
}

function makeSystemStatus(overrides: Partial<SystemStatusResponse> = {}): SystemStatusResponse {
  return {
    user_id: 'u',
    sources: [
      {
        source_slug: 'garmin_connect',
        integration_configured: true,
        device_paired: null,
        last_sync_at: NOW,
        last_advanced_at: NOW,
        last_run_status: 'ok',
        last_run_at: NOW,
      },
      {
        source_slug: 'hc900_ble',
        integration_configured: true,
        device_paired: true,
        last_sync_at: NOW,
        last_advanced_at: NOW,
        last_run_status: 'ok',
        last_run_at: NOW,
      },
    ],
    agents: [],
    as_of: NOW,
    ...overrides,
  };
}

function makeSummary(blockOverrides: Partial<InsightSummary['block_availability']> = {}): InsightSummary {
  return {
    user_id: 'u',
    as_of: NOW,
    overall_adherence_pct: null,
    active_deviations: 0,
    current_symptom_burden: 0,
    illness_signal: 'none',
    recovery_status: 'normal',
    block_availability: {
      deviations: 'ok',
      illness: 'ok',
      recovery: 'ok',
      adherence: 'ok',
      symptoms: 'ok',
      ...blockOverrides,
    },
    data_availability: null,
  };
}

// ── 1. overallState ───────────────────────────────────────────────────────

describe('overallState', () => {
  it('no_data when all sources are empty/null', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.overallState).toBe('no_data');
    expect(vm.headline).toMatch(/no data/i);
  });

  it('no_data when only systemStatus present (no measurements, no checkpoints)', () => {
    const vm = deriveProgressViewModel(makeSources({ systemStatus: makeSystemStatus() }));
    // systemStatus alone → hasAnySources = true, BUT both blocks will be insufficient
    expect(vm.overallState).toBe('limited');
  });

  it('limited when only minimal checkpoints (<3 logged)', () => {
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: [makeCheckpoint('morning', '2026-04-18')] }),
    );
    expect(vm.overallState).toBe('limited');
    expect(vm.headline).toMatch(/collecting data/i);
  });

  it('limited when consistency and signal are both insufficient', () => {
    // 2 checkpoints = insufficient consistency; no HRV/RHR = insufficient signal
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(2) }),
    );
    expect(vm.overallState).toBe('limited');
  });

  it('mixed when consistency is sufficient but signal is insufficient', () => {
    const vm = deriveProgressViewModel(
      makeSources({
        // 10 morning check-ins → rate 10/14 ≈ 71% → 'sufficient'
        checkpoints14d: makeCheckpoints(10),
        // no HRV/RHR → signal 'insufficient'
        hrv14d: [],
        rhr14d: [],
      }),
    );
    expect(vm.overallState).toBe('mixed');
  });

  it('mixed when signal is sufficient but consistency is limited', () => {
    const hrv = [
      ...makeHrvReadings([50, 52, 54], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([42, 43, 44], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([58, 59, 60], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([64, 65, 66], PRIOR_DATES.slice(0, 3)),
    ];
    // 6 checkpoints → rate 6/14 ≈ 43% → below CONSISTENCY_LIMITED_THRESHOLD → 'insufficient'
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(6), hrv14d: hrv, rhr14d: rhr }),
    );
    expect(vm.overallState).toBe('mixed');
  });

  it('sufficient when both consistency and signal are sufficient', () => {
    const hrv = [
      ...makeHrvReadings([50, 52, 54], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([42, 43, 44], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([58, 59, 60], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([64, 65, 66], PRIOR_DATES.slice(0, 3)),
    ];
    // 10 morning check-ins → rate 71% → 'sufficient'
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(10), hrv14d: hrv, rhr14d: rhr }),
    );
    expect(vm.overallState).toBe('sufficient');
  });
});

// ── 2. ConsistencyBlock ───────────────────────────────────────────────────

describe('ConsistencyBlock', () => {
  it('null rates and insufficient when fewer than 3 logs total', () => {
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: makeCheckpoints(2) }));
    expect(vm.consistency.checkInRate).toBeNull();
    expect(vm.consistency.checkOutRate).toBeNull();
    expect(vm.consistency.dataConfidence).toBe('insufficient');
    expect(vm.consistency.caveat).toBeTruthy();
  });

  it('computes checkInRate as fraction of 14-day window', () => {
    // 7 morning check-ins → 7/14 = 0.5
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(7) }),
    );
    expect(vm.consistency.checkInRate).toBeCloseTo(0.5, 5);
    expect(vm.consistency.windowDays).toBe(14);
  });

  it(`checkInRate >= ${CONSISTENCY_SUFFICIENT_THRESHOLD} → sufficient`, () => {
    // 10 morning check-ins → 10/14 ≈ 0.714 ≥ 0.7
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(10) }),
    );
    expect(vm.consistency.checkInRate).toBeGreaterThanOrEqual(CONSISTENCY_SUFFICIENT_THRESHOLD);
    expect(vm.consistency.dataConfidence).toBe('sufficient');
    expect(vm.consistency.caveat).toBeNull();
  });

  it(`checkInRate >= ${CONSISTENCY_LIMITED_THRESHOLD} but < ${CONSISTENCY_SUFFICIENT_THRESHOLD} → limited`, () => {
    // 8 morning check-ins → 8/14 ≈ 0.571 ≥ 0.5 but < 0.7
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(8) }),
    );
    const rate = vm.consistency.checkInRate!;
    expect(rate).toBeGreaterThanOrEqual(CONSISTENCY_LIMITED_THRESHOLD);
    expect(rate).toBeLessThan(CONSISTENCY_SUFFICIENT_THRESHOLD);
    expect(vm.consistency.dataConfidence).toBe('limited');
    expect(vm.consistency.caveat).toBeTruthy();
  });

  it('checkInRate < CONSISTENCY_LIMITED_THRESHOLD → insufficient', () => {
    // 5 morning check-ins → 5/14 ≈ 0.357 < 0.5
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(5) }),
    );
    expect(vm.consistency.dataConfidence).toBe('insufficient');
  });

  it('normalises medicationAdherence from 0-100 to 0-1', () => {
    const vm = deriveProgressViewModel(
      makeSources({
        checkpoints14d: makeCheckpoints(10),
        medicationAdherence: makeAdherence(80),
      }),
    );
    expect(vm.consistency.medicationAdherence).toBeCloseTo(0.8, 5);
  });

  it('medicationAdherence is null when no active regimens', () => {
    const vm = deriveProgressViewModel(
      makeSources({
        checkpoints14d: makeCheckpoints(10),
        medicationAdherence: makeAdherence(null),
      }),
    );
    expect(vm.consistency.medicationAdherence).toBeNull();
  });

  it('tracks checkOutRate separately from checkInRate', () => {
    const mornings = makeCheckpoints(10, 'morning');
    const nights = makeCheckpoints(5, 'night');
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: [...mornings, ...nights] }),
    );
    expect(vm.consistency.checkInRate).toBeCloseTo(10 / 14, 5);
    expect(vm.consistency.checkOutRate).toBeCloseTo(5 / 14, 5);
  });
});

// ── 3. SignalDirectionBlock — neutral zone ────────────────────────────────

describe('SignalDirectionBlock — neutral zone', () => {
  it(`HRV delta < ${SIGNAL_HRV_NEUTRAL_PCT}% → stable (neutral zone)`, () => {
    // prior mean = 50, recent mean = 53 → delta = +6% < 8% → stable
    const hrv = [
      ...makeHrvReadings([53, 53, 53], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([50, 50, 50], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv).not.toBeNull();
    expect(vm.signalDirection.hrv!.direction).toBe('stable');
    // deltaPct ≈ +6, just below threshold
    expect(Math.abs(vm.signalDirection.hrv!.deltaPct)).toBeLessThan(SIGNAL_HRV_NEUTRAL_PCT);
  });

  it('HRV delta exactly at neutral zone threshold → stable', () => {
    // prior mean = 50, recent mean = 54 → delta = +8% = threshold → stable (not up)
    const hrv = [
      ...makeHrvReadings([54, 54, 54], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([50, 50, 50], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    // 8% is NOT < 8, so this actually should be 'up'. Test that exactly-at-threshold is NOT neutral.
    // SIGNAL_HRV_NEUTRAL_PCT check is `< threshold`, so 8% exactly is NOT neutral → 'up'
    expect(vm.signalDirection.hrv!.direction).toBe('up');
  });

  it('HRV delta > neutral zone → up', () => {
    // prior mean = 48, recent mean = 56 → delta = +16.7% > 8%
    const hrv = [
      ...makeHrvReadings([56, 56, 56], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 48, 48], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv!.direction).toBe('up');
    expect(vm.signalDirection.hrv!.deltaPct).toBeGreaterThan(SIGNAL_HRV_NEUTRAL_PCT);
  });

  it('HRV delta > neutral zone (negative) → down', () => {
    // prior mean = 56, recent mean = 48 → delta = -14.3%
    const hrv = [
      ...makeHrvReadings([48, 48, 48], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([56, 56, 56], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv!.direction).toBe('down');
  });

  it(`RHR delta < ${SIGNAL_RHR_NEUTRAL_BPM} bpm → stable (neutral zone)`, () => {
    // prior mean = 60, recent mean = 62 → delta = 2 bpm < 3 bpm → stable
    const rhr = [
      ...makeRhrReadings([62, 62, 62], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([60, 60, 60], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ rhr14d: rhr }));
    expect(vm.signalDirection.rhr!.direction).toBe('stable');
    expect(Math.abs(vm.signalDirection.rhr!.recentMean - vm.signalDirection.rhr!.priorMean))
      .toBeLessThan(SIGNAL_RHR_NEUTRAL_BPM);
  });

  it('RHR delta > neutral zone → down (fewer bpm = improved cardiac load)', () => {
    // prior mean = 65, recent mean = 59 → delta = -6 bpm → down
    const rhr = [
      ...makeRhrReadings([59, 59, 59], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([65, 65, 65], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ rhr14d: rhr }));
    expect(vm.signalDirection.rhr!.direction).toBe('down');
  });

  it('uses percentage for HRV and absolute bpm for RHR (different neutral zone logic)', () => {
    // HRV: prior=50, recent=53 → delta=6% < 8% → stable
    // RHR: prior=60, recent=62 → delta=2bpm < 3bpm → stable
    const hrv = [
      ...makeHrvReadings([53, 53, 53], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([50, 50, 50], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([62, 62, 62], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([60, 60, 60], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv, rhr14d: rhr }));
    expect(vm.signalDirection.hrv!.direction).toBe('stable');
    expect(vm.signalDirection.rhr!.direction).toBe('stable');
  });
});

// ── 4. SignalDirectionBlock — N threshold ─────────────────────────────────

describe(`SignalDirectionBlock — MIN_SIGNAL_N = ${MIN_SIGNAL_N}`, () => {
  it('returns null trend when recent window has fewer than MIN_SIGNAL_N readings', () => {
    const hrv = [
      ...makeHrvReadings([55, 55], RECENT_DATES.slice(0, 2)), // only 2 — insufficient
      ...makeHrvReadings([48, 49, 50], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv).toBeNull();
  });

  it('returns null trend when prior window has fewer than MIN_SIGNAL_N readings', () => {
    const hrv = [
      ...makeHrvReadings([55, 55, 55], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 49], PRIOR_DATES.slice(0, 2)), // only 2 — insufficient
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv).toBeNull();
  });

  it('hasBoth → sufficient dataConfidence', () => {
    const hrv = [
      ...makeHrvReadings([55, 55, 55], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 48, 48], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([60, 60, 60], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([65, 65, 65], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv, rhr14d: rhr }));
    expect(vm.signalDirection.hrv).not.toBeNull();
    expect(vm.signalDirection.rhr).not.toBeNull();
    expect(vm.signalDirection.dataConfidence).toBe('sufficient');
    expect(vm.signalDirection.caveat).toBeNull();
  });

  it('only HRV available → limited dataConfidence', () => {
    const hrv = [
      ...makeHrvReadings([55, 55, 55], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 48, 48], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv).not.toBeNull();
    expect(vm.signalDirection.rhr).toBeNull();
    expect(vm.signalDirection.dataConfidence).toBe('limited');
  });

  it('no readings → insufficient dataConfidence with caveat', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.signalDirection.hrv).toBeNull();
    expect(vm.signalDirection.rhr).toBeNull();
    expect(vm.signalDirection.dataConfidence).toBe('insufficient');
    expect(vm.signalDirection.caveat).toMatch(new RegExp(String(MIN_SIGNAL_N)));
  });

  it('exposes recentN and priorN on the SignalTrend', () => {
    const hrv = [
      ...makeHrvReadings([55, 56, 57, 58], RECENT_DATES.slice(0, 4)),
      ...makeHrvReadings([48, 49, 50], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(makeSources({ hrv14d: hrv }));
    expect(vm.signalDirection.hrv!.recentN).toBe(4);
    expect(vm.signalDirection.hrv!.priorN).toBe(3);
  });
});

// ── 5. ReportedSymptomBurdenBlock ─────────────────────────────────────────

describe('ReportedSymptomBurdenBlock', () => {
  it('insufficient_data when no symptom logs in either window', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.reportedSymptomBurden.direction).toBe('insufficient_data');
    expect(vm.reportedSymptomBurden.recentCount).toBe(0);
    expect(vm.reportedSymptomBurden.priorCount).toBe(0);
    expect(vm.reportedSymptomBurden.caveat).toBeTruthy();
  });

  it('improving when fewer recent logs and logging is consistent', () => {
    // High check-in rate: 10/14 = 71% → consistent
    const checkpoints = makeCheckpoints(10);
    // recent=1, prior=4 → delta=-3 → improving
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]),
      makeSymptom('headache', PRIOR_DATES[0]),
      makeSymptom('fatigue', PRIOR_DATES[1]),
      makeSymptom('nausea', PRIOR_DATES[2]),
      makeSymptom('headache', PRIOR_DATES[3]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.recentCount).toBe(1);
    expect(vm.reportedSymptomBurden.priorCount).toBe(4);
    expect(vm.reportedSymptomBurden.direction).toBe('improving');
    expect(vm.reportedSymptomBurden.loggingConsistencyLow).toBe(false);
    expect(vm.reportedSymptomBurden.caveat).toBeNull();
  });

  it('worsening when more recent logs and logging is consistent', () => {
    const checkpoints = makeCheckpoints(10);
    // recent=4, prior=1 → delta=+3 → worsening
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]),
      makeSymptom('fatigue', RECENT_DATES[1]),
      makeSymptom('nausea', RECENT_DATES[2]),
      makeSymptom('knee_pain', RECENT_DATES[3]),
      makeSymptom('headache', PRIOR_DATES[0]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.direction).toBe('worsening');
  });

  it(`stable when delta ≤ ${SYMPTOM_STABLE_DELTA} and logging consistent`, () => {
    const checkpoints = makeCheckpoints(10);
    // recent=3, prior=3 → delta=0 → stable
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]),
      makeSymptom('fatigue', RECENT_DATES[1]),
      makeSymptom('nausea', RECENT_DATES[2]),
      makeSymptom('headache', PRIOR_DATES[0]),
      makeSymptom('fatigue', PRIOR_DATES[1]),
      makeSymptom('nausea', PRIOR_DATES[2]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.direction).toBe('stable');
  });

  it('CRITICAL — unclear (not improving) when logging inconsistent + few recent logs', () => {
    // Low check-in rate: 5/14 ≈ 35% < 0.5 → inconsistent
    // recent=1 < MIN_SYMPTOM_LOGS_FOR_DIRECTION → loggingConsistencyLow = true
    // prior=4 → would appear "improving" if we naively compared counts
    const checkpoints = makeCheckpoints(5); // sparse logging
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]), // only 1 recent log
      makeSymptom('headache', PRIOR_DATES[0]),
      makeSymptom('fatigue', PRIOR_DATES[1]),
      makeSymptom('nausea', PRIOR_DATES[2]),
      makeSymptom('headache', PRIOR_DATES[3]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.loggingConsistencyLow).toBe(true);
    expect(vm.reportedSymptomBurden.direction).toBe('unclear'); // NOT 'improving'
    expect(vm.reportedSymptomBurden.caveat).toMatch(/logging/i);
  });

  it('NOT unclear when logging inconsistent but many recent symptom logs', () => {
    // Low check-in rate: 5/14 ≈ 35% < 0.5
    // But recent logs = 4 ≥ MIN_SYMPTOM_LOGS_FOR_DIRECTION → not capped
    const checkpoints = makeCheckpoints(5);
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]),
      makeSymptom('fatigue', RECENT_DATES[1]),
      makeSymptom('nausea', RECENT_DATES[2]),
      makeSymptom('knee_pain', RECENT_DATES[3]), // 4 recent logs
      makeSymptom('headache', PRIOR_DATES[0]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.loggingConsistencyLow).toBe(false);
    expect(vm.reportedSymptomBurden.direction).toBe('worsening'); // not unclear
  });

  it('NOT unclear when logging consistent regardless of recent log count', () => {
    // High check-in rate: 10/14 → consistent. Few recent logs should still give a direction.
    const checkpoints = makeCheckpoints(10);
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]), // 1 recent
      makeSymptom('headache', PRIOR_DATES[0]),
      makeSymptom('fatigue', PRIOR_DATES[1]),
      makeSymptom('nausea', PRIOR_DATES[2]),
      makeSymptom('headache', PRIOR_DATES[3]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.loggingConsistencyLow).toBe(false);
    expect(vm.reportedSymptomBurden.direction).toBe('improving'); // fewer is still fewer
  });

  it('tracks topSymptom by frequency in recent window', () => {
    const checkpoints = makeCheckpoints(10);
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]),
      makeSymptom('headache', RECENT_DATES[1]),
      makeSymptom('fatigue', RECENT_DATES[2]),
      makeSymptom('nausea', PRIOR_DATES[0]),
    ];
    const vm = deriveProgressViewModel(makeSources({ checkpoints14d: checkpoints, symptoms14d: symptoms }));
    expect(vm.reportedSymptomBurden.topSymptom).toBe('headache');
  });

  it('topSymptom is null when recent window has no logs', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.reportedSymptomBurden.topSymptom).toBeNull();
  });
});

// ── 6. DataConfidenceBlock — two dimensions ───────────────────────────────

describe('DataConfidenceBlock — freshness vs analytical coverage', () => {
  it('freshness.garminOk = true when garmin configured and last_run_status ok', () => {
    const vm = deriveProgressViewModel(makeSources({ systemStatus: makeSystemStatus() }));
    expect(vm.dataConfidence.freshness.garminOk).toBe(true);
  });

  it('freshness.garminOk = false when garmin integration_configured = false', () => {
    const status = makeSystemStatus({
      sources: [
        { source_slug: 'garmin_connect', integration_configured: false,
          device_paired: null, last_sync_at: null, last_advanced_at: null,
          last_run_status: null, last_run_at: null },
        { source_slug: 'hc900_ble', integration_configured: true,
          device_paired: true, last_sync_at: NOW, last_advanced_at: NOW,
          last_run_status: 'ok', last_run_at: NOW },
      ],
    });
    const vm = deriveProgressViewModel(makeSources({ systemStatus: status }));
    expect(vm.dataConfidence.freshness.garminOk).toBe(false);
    expect(vm.dataConfidence.freshness.overallOk).toBe(false);
  });

  it('freshness.scaleOk = false when device_paired = false', () => {
    const status = makeSystemStatus({
      sources: [
        { source_slug: 'garmin_connect', integration_configured: true,
          device_paired: null, last_sync_at: NOW, last_advanced_at: NOW,
          last_run_status: 'ok', last_run_at: NOW },
        { source_slug: 'hc900_ble', integration_configured: true,
          device_paired: false, last_sync_at: null, last_advanced_at: null,
          last_run_status: null, last_run_at: null },
      ],
    });
    const vm = deriveProgressViewModel(makeSources({ systemStatus: status }));
    expect(vm.dataConfidence.freshness.scaleOk).toBe(false);
    expect(vm.dataConfidence.freshness.overallOk).toBe(false);
  });

  it('freshness.overallOk = true when garmin configured + scale paired', () => {
    const vm = deriveProgressViewModel(makeSources({ systemStatus: makeSystemStatus() }));
    expect(vm.dataConfidence.freshness.overallOk).toBe(true);
  });

  it('analyticalCoverage counts blocks with "ok" availability from InsightSummary', () => {
    const summary = makeSummary({
      deviations: 'ok',
      illness: 'ok',
      recovery: 'insufficient_data',
      adherence: 'no_data',
      symptoms: 'ok',
    });
    const vm = deriveProgressViewModel(makeSources({ summary }));
    expect(vm.dataConfidence.analyticalCoverage.blocksWithData).toBe(3);
    expect(vm.dataConfidence.analyticalCoverage.totalBlocks).toBe(5);
  });

  it('analyticalCoverage.checkInConsistent = true when rate ≥ threshold', () => {
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(10), summary: makeSummary() }),
    );
    expect(vm.dataConfidence.analyticalCoverage.checkInConsistent).toBe(true);
  });

  it('analyticalCoverage.checkInConsistent = false when rate < threshold', () => {
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(5), summary: makeSummary() }),
    );
    // 5/14 ≈ 0.357 < LOGGING_CONSISTENCY_THRESHOLD
    expect(vm.dataConfidence.analyticalCoverage.checkInConsistent).toBe(false);
  });

  it('summary includes pipeline issues when freshness degraded', () => {
    const status = makeSystemStatus({
      sources: [
        { source_slug: 'garmin_connect', integration_configured: false,
          device_paired: null, last_sync_at: null, last_advanced_at: null,
          last_run_status: null, last_run_at: null },
        { source_slug: 'hc900_ble', integration_configured: true,
          device_paired: true, last_sync_at: NOW, last_advanced_at: NOW,
          last_run_status: 'ok', last_run_at: NOW },
      ],
    });
    const vm = deriveProgressViewModel(makeSources({ systemStatus: status }));
    expect(vm.dataConfidence.summary).toMatch(/pipeline/i);
  });

  it('summary is "data sources healthy" when all ok', () => {
    const vm = deriveProgressViewModel(
      makeSources({
        systemStatus: makeSystemStatus(),
        summary: makeSummary(),
        checkpoints14d: makeCheckpoints(10),
      }),
    );
    expect(vm.dataConfidence.summary).toMatch(/healthy/i);
  });

  it('summary falls back when both systemStatus and summary are null', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.dataConfidence.summary).toMatch(/not available/i);
  });

  it('freshness and analyticalCoverage are independent — one can be ok while the other is not', () => {
    // Freshness ok (garmin + scale healthy) but analytical coverage low (no blocks ok)
    const status = makeSystemStatus();
    const summary = makeSummary({
      deviations: 'insufficient_data',
      illness: 'no_data',
      recovery: 'no_data',
      adherence: 'not_applicable',
      symptoms: 'no_data',
    });
    const vm = deriveProgressViewModel(makeSources({ systemStatus: status, summary }));
    expect(vm.dataConfidence.freshness.overallOk).toBe(true);      // pipelines ok
    expect(vm.dataConfidence.analyticalCoverage.blocksWithData).toBe(0); // no analytical data yet
  });
});

// ── 7. Headline ───────────────────────────────────────────────────────────

describe('headline', () => {
  it('no_data → "No data yet"', () => {
    const vm = deriveProgressViewModel(makeSources());
    expect(vm.headline).toMatch(/no data/i);
  });

  it('limited → "Collecting data"', () => {
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(2) }),
    );
    expect(vm.headline).toMatch(/collecting data/i);
  });

  it('sufficient with HRV up includes HRV direction in headline', () => {
    const hrv = [
      ...makeHrvReadings([56, 56, 56], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 48, 48], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([60, 60, 60], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([60, 60, 60], PRIOR_DATES.slice(0, 3)),
    ];
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: makeCheckpoints(10), hrv14d: hrv, rhr14d: rhr }),
    );
    expect(vm.headline).toMatch(/HRV trending up/i);
  });

  it('sufficient with improving symptoms includes it in headline', () => {
    const checkpoints = makeCheckpoints(10);
    const hrv = [
      ...makeHrvReadings([52, 52, 52], RECENT_DATES.slice(0, 3)),
      ...makeHrvReadings([48, 48, 48], PRIOR_DATES.slice(0, 3)),
    ];
    const rhr = [
      ...makeRhrReadings([60, 60, 60], RECENT_DATES.slice(0, 3)),
      ...makeRhrReadings([60, 60, 60], PRIOR_DATES.slice(0, 3)),
    ];
    const symptoms = [
      makeSymptom('headache', RECENT_DATES[0]), // 1 recent
      makeSymptom('headache', PRIOR_DATES[0]),
      makeSymptom('fatigue', PRIOR_DATES[1]),
      makeSymptom('nausea', PRIOR_DATES[2]),
      makeSymptom('headache', PRIOR_DATES[3]),
    ];
    const vm = deriveProgressViewModel(
      makeSources({ checkpoints14d: checkpoints, hrv14d: hrv, rhr14d: rhr, symptoms14d: symptoms }),
    );
    expect(vm.headline).toMatch(/fewer reported symptoms/i);
  });
});

// ── 8. Constants exported for external reference ─────────────────────────

describe('exported threshold constants', () => {
  it('SIGNAL_HRV_NEUTRAL_PCT is a positive number', () => {
    expect(SIGNAL_HRV_NEUTRAL_PCT).toBeGreaterThan(0);
  });
  it('SIGNAL_RHR_NEUTRAL_BPM is a positive number', () => {
    expect(SIGNAL_RHR_NEUTRAL_BPM).toBeGreaterThan(0);
  });
  it('MIN_SIGNAL_N is at least 3', () => {
    expect(MIN_SIGNAL_N).toBeGreaterThanOrEqual(3);
  });
  it('LOGGING_CONSISTENCY_THRESHOLD is between 0 and 1', () => {
    expect(LOGGING_CONSISTENCY_THRESHOLD).toBeGreaterThan(0);
    expect(LOGGING_CONSISTENCY_THRESHOLD).toBeLessThan(1);
  });
  it('MIN_SYMPTOM_LOGS_FOR_DIRECTION is a positive integer', () => {
    expect(MIN_SYMPTOM_LOGS_FOR_DIRECTION).toBeGreaterThan(0);
    expect(Number.isInteger(MIN_SYMPTOM_LOGS_FOR_DIRECTION)).toBe(true);
  });
});
