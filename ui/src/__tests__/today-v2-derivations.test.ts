import { describe, it, expect } from 'vitest';
import {
  deriveBlockers,
  deriveCompletion,
  deriveHero,
  deriveSurfaceState,
  deriveTodayViewModel,
  deriveTrust,
  prioritizeActions,
} from '../features/today/deriveTodayViewModel';
import {
  defaultDailyProtocol,
  PROTOCOL_KINDS,
  type DailyProtocol,
  type TodayRawSources,
} from '../features/today/types';
import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementResponse,
  MedicationLogResponse,
  MedicationRegimenResponse,
  SymptomLogResponse,
  SystemAgentSummary,
  SystemSourceStatus,
  SystemStatusResponse,
} from '../api/types';

// ── Time anchors (UTC) ────────────────────────────────────────────────────
// Default protocol windows: checkIn.windowEnd = 15:00 UTC,
// checkOut.windowStart = 23:00 UTC.

const DATE = '2026-04-17';
const NOW_MORNING = '2026-04-17T10:00:00.000Z'; // before checkIn window end
const NOW_AFTERNOON = '2026-04-17T18:00:00.000Z'; // after checkIn, before checkOut
const NOW_NIGHT = '2026-04-17T23:30:00.000Z'; // after checkOut window start

// ── Fixture builders ──────────────────────────────────────────────────────

function makeSources(overrides: Partial<TodayRawSources> = {}): TodayRawSources {
  return {
    date: DATE,
    now: NOW_AFTERNOON,
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

function makeCheckpoint(
  type: 'morning' | 'night',
  overrides: Partial<DailyCheckpointResponse> = {},
): DailyCheckpointResponse {
  return {
    id: `cp-${type}`,
    user_id: 'u',
    checkpoint_type: type,
    checkpoint_date: DATE,
    checkpoint_at: `${DATE}T${type === 'morning' ? '08' : '22'}:00:00.000Z`,
    mood: null,
    energy: null,
    sleep_quality: null,
    body_state_score: null,
    notes: null,
    ...overrides,
  };
}

function makeMeasurement(
  slug: string,
  value: number,
  measuredAt: string,
  overrides: Partial<MeasurementResponse> = {},
): MeasurementResponse {
  return {
    id: `m-${slug}-${measuredAt}`,
    user_id: 'u',
    metric_type_slug: slug,
    metric_type_name: slug,
    source_slug: slug === 'weight' ? 'hc900_ble' : 'garmin_connect',
    value_num: value,
    unit: slug === 'weight' ? 'kg' : slug === 'body_temperature' ? '°C' : 'ms',
    measured_at: measuredAt,
    aggregation_level: 'raw',
    ...overrides,
  };
}

function makeSymptom(
  overrides: Partial<SymptomLogResponse> = {},
): SymptomLogResponse {
  return {
    id: 'sym-1',
    user_id: 'u',
    symptom_slug: 'headache',
    symptom_name: 'Headache',
    intensity: 2,
    status: 'active',
    started_at: `${DATE}T09:00:00.000Z`,
    ...overrides,
  };
}

function makeRegimen(
  overrides: Partial<MedicationRegimenResponse> = {},
): MedicationRegimenResponse {
  return {
    id: 'reg-1',
    user_id: 'u',
    medication_id: 1,
    medication_name: 'Vitamin D',
    dosage_amount: 1,
    dosage_unit: 'capsule',
    frequency: 'daily',
    instructions: null,
    prescribed_by: null,
    started_at: `${DATE}T00:00:00.000Z`,
    ended_at: null,
    is_active: true,
    created_at: `${DATE}T00:00:00.000Z`,
    updated_at: `${DATE}T00:00:00.000Z`,
    ...overrides,
  };
}

function makeMedLog(regimenId: string, scheduledAt: string): MedicationLogResponse {
  return {
    id: `log-${regimenId}`,
    user_id: 'u',
    regimen_id: regimenId,
    status: 'taken',
    scheduled_at: scheduledAt,
    taken_at: scheduledAt,
    dosage_amount: null,
    dosage_unit: null,
    notes: null,
    recorded_at: scheduledAt,
    ingested_at: scheduledAt,
  };
}

function makeSource(
  source_slug: string,
  overrides: Partial<SystemSourceStatus> = {},
): SystemSourceStatus {
  return {
    source_slug,
    integration_configured: true,
    device_paired: source_slug === 'hc900_ble' ? true : null,
    last_sync_at: NOW_AFTERNOON,
    last_advanced_at: NOW_AFTERNOON,
    last_run_status: 'ok',
    last_run_at: NOW_AFTERNOON,
    ...overrides,
  };
}

function makeAgent(
  agent_type: string,
  status: SystemAgentSummary['status'] = 'active',
): SystemAgentSummary {
  return {
    agent_type,
    display_name: agent_type,
    status,
    last_seen_at: NOW_AFTERNOON,
  };
}

function makeSystemStatus(
  overrides: Partial<SystemStatusResponse> = {},
): SystemStatusResponse {
  return {
    user_id: 'u',
    sources: [makeSource('garmin_connect'), makeSource('hc900_ble')],
    agents: [makeAgent('garmin_sync')],
    as_of: NOW_AFTERNOON,
    ...overrides,
  };
}

function makeScaleReading(weightKg = 75): LatestScaleReading {
  return {
    status: 'full_reading',
    measured_at: `${DATE}T07:00:00.000Z`,
    raw_payload_id: 'p-1',
    decoder_version: 'hc900/v1',
    has_impedance: true,
    metrics: {
      weight: { slug: 'weight', value: String(weightKg), unit: 'kg', is_derived: false },
    },
  };
}

// ── Contract presence ─────────────────────────────────────────────────────

describe('Today v2 · contract presence', () => {
  it('DailyProtocol includes check_in, check_out, symptoms and the other five kinds', () => {
    const p = defaultDailyProtocol(DATE);
    expect(p.checkIn).toBeDefined();
    expect(p.checkOut).toBeDefined();
    expect(p.symptoms).toBeDefined();
    expect(p.medication).toBeDefined();
    expect(p.temperature).toBeDefined();
    expect(p.weight).toBeDefined();
    expect(p.garmin).toBeDefined();
    expect(PROTOCOL_KINDS).toEqual([
      'check_in',
      'check_out',
      'medication',
      'temperature',
      'symptoms',
      'weight',
      'garmin',
    ]);
  });

  it('deriveCompletion returns exactly one entry per protocol kind', () => {
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), makeSources());
    const kinds = vm.completion.map((c) => c.kind).sort();
    expect(kinds).toEqual([...PROTOCOL_KINDS].sort());
  });
});

// ── State: empty, partial, complete day ──────────────────────────────────

describe('Today v2 · empty day with active protocol', () => {
  it('state=action_needed, all required items missing or not_applicable', () => {
    const vm = deriveTodayViewModel(
      defaultDailyProtocol(DATE),
      makeSources({ now: NOW_MORNING, systemStatus: makeSystemStatus() }),
    );

    expect(vm.state).toBe('action_needed');

    const byKind = Object.fromEntries(vm.completion.map((c) => [c.kind, c]));
    expect(byKind.check_in.status).toBe('missing');
    expect(byKind.check_out.status).toBe('missing');
    // medication: no active regimens ⇒ not_applicable (even with required=true)
    expect(byKind.medication.status).toBe('not_applicable');
    expect(byKind.temperature.status).toBe('not_applicable'); // not required by default
    expect(byKind.symptoms.status).toBe('not_applicable'); // opt-in
    expect(byKind.weight.status).toBe('missing');
    expect(byKind.garmin.status).toBe('missing');

    expect(vm.priorityActions.length).toBeGreaterThan(0);
    expect(vm.hero.kind).toBe('action');
  });
});

describe('Today v2 · partial day', () => {
  it('morning logged, rest missing ⇒ action_needed; completion reflects morning', () => {
    const sources = makeSources({
      now: NOW_AFTERNOON,
      checkpointsToday: [makeCheckpoint('morning')],
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    const byKind = Object.fromEntries(vm.completion.map((c) => [c.kind, c]));
    expect(byKind.check_in.status).toBe('complete');
    expect(byKind.check_out.status).toBe('missing');
    expect(byKind.weight.status).toBe('missing');
    expect(vm.state).toBe('action_needed');
    expect(vm.priorityActions.find((a) => a.kind === 'check_in')).toBeUndefined();
    expect(vm.priorityActions.find((a) => a.kind === 'weight')).toBeDefined();
  });
});

describe('Today v2 · complete day', () => {
  it('all required complete ⇒ state=ok and hero=confirmation', () => {
    const sources = makeSources({
      now: NOW_NIGHT,
      checkpointsToday: [makeCheckpoint('morning'), makeCheckpoint('night')],
      weightToday: [makeMeasurement('weight', 75.2, `${DATE}T07:00:00.000Z`)],
      latestScaleReading: makeScaleReading(75.2),
      garminMetricsToday: [
        makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`),
      ],
      latestHrvMeasurement: makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`),
      systemStatus: makeSystemStatus(),
      // No regimens ⇒ medication not_applicable.
      activeRegimens: [],
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    expect(vm.state).toBe('ok');
    expect(vm.priorityActions).toHaveLength(0);
    expect(vm.hero.kind).toBe('confirmation');
    if (vm.hero.kind === 'confirmation') {
      expect(vm.hero.message).toBe('Day on track');
    }
  });
});

// ── Per-kind scenarios ────────────────────────────────────────────────────

describe('Today v2 · medication partial', () => {
  it('one of two regimens logged today ⇒ partial with action', () => {
    const sources = makeSources({
      activeRegimens: [
        makeRegimen({ id: 'r1', medication_name: 'Vit D' }),
        makeRegimen({ id: 'r2', medication_id: 2, medication_name: 'Iron' }),
      ],
      medicationLogsToday: [makeMedLog('r1', `${DATE}T10:00:00.000Z`)],
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    const med = vm.completion.find((c) => c.kind === 'medication')!;
    expect(med.status).toBe('partial');
    expect(med.detail).toContain('1 of 2');
    expect(vm.priorityActions.find((a) => a.kind === 'medication')).toBeDefined();
  });
});

describe('Today v2 · required temperature missing', () => {
  it('protocol requires temp, none logged ⇒ missing + action', () => {
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
      temperature: { required: true, minReadings: 1 },
    };
    const sources = makeSources({ systemStatus: makeSystemStatus() });
    const vm = deriveTodayViewModel(protocol, sources);

    const temp = vm.completion.find((c) => c.kind === 'temperature')!;
    expect(temp.status).toBe('missing');
    expect(vm.priorityActions.find((a) => a.kind === 'temperature')).toBeDefined();
  });

  it('partial when some readings logged but below minReadings', () => {
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
      temperature: { required: true, minReadings: 3 },
    };
    const sources = makeSources({
      temperatureToday: [
        makeMeasurement('body_temperature', 36.6, `${DATE}T09:00:00.000Z`),
      ],
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(protocol, sources);

    const temp = vm.completion.find((c) => c.kind === 'temperature')!;
    expect(temp.status).toBe('partial');
    expect(temp.detail).toContain('1 of 3');
  });
});

describe('Today v2 · required weight, scale operational', () => {
  it('no weight today but scale paired ⇒ missing + action, no blocker', () => {
    const sources = makeSources({
      systemStatus: makeSystemStatus({
        sources: [
          makeSource('garmin_connect'),
          makeSource('hc900_ble', { device_paired: true }),
        ],
      }),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    const weight = vm.completion.find((c) => c.kind === 'weight')!;
    expect(weight.status).toBe('missing');
    expect(vm.priorityActions.find((a) => a.kind === 'weight')).toBeDefined();
    expect(vm.blockers.find((b) => b.kind === 'weight')).toBeUndefined();
  });
});

describe('Today v2 · required weight, scale blocked', () => {
  it('no weight + scale unpaired ⇒ blocked + blocker, no weight action', () => {
    const sources = makeSources({
      systemStatus: makeSystemStatus({
        sources: [
          makeSource('garmin_connect'),
          makeSource('hc900_ble', { device_paired: false }),
        ],
      }),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    const weight = vm.completion.find((c) => c.kind === 'weight')!;
    expect(weight.status).toBe('blocked');
    expect(vm.blockers.find((b) => b.kind === 'weight')).toBeDefined();
    expect(vm.priorityActions.find((a) => a.kind === 'weight')).toBeUndefined();
  });
});

describe('Today v2 · garmin required', () => {
  it('HRV today ⇒ complete', () => {
    const hrv = makeMeasurement('hrv_rmssd', 52, `${DATE}T06:00:00.000Z`);
    const sources = makeSources({
      garminMetricsToday: [hrv],
      latestHrvMeasurement: hrv,
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);
    expect(vm.completion.find((c) => c.kind === 'garmin')!.status).toBe('complete');
  });

  it('garmin metrics today but no HRV ⇒ partial + action', () => {
    const rhr = makeMeasurement('resting_hr', 62, `${DATE}T06:00:00.000Z`);
    const sources = makeSources({
      garminMetricsToday: [rhr],
      latestHrvMeasurement: makeMeasurement(
        'hrv_rmssd',
        55,
        '2026-04-15T06:00:00.000Z',
      ),
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);
    const garmin = vm.completion.find((c) => c.kind === 'garmin')!;
    expect(garmin.status).toBe('partial');
    expect(vm.priorityActions.find((a) => a.kind === 'garmin')).toBeDefined();
  });

  it('no garmin data today ⇒ missing + action', () => {
    const sources = makeSources({ systemStatus: makeSystemStatus() });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);
    expect(vm.completion.find((c) => c.kind === 'garmin')!.status).toBe('missing');
    expect(vm.priorityActions.find((a) => a.kind === 'garmin')).toBeDefined();
  });
});

describe('Today v2 · garmin stale but not required', () => {
  it('not required ⇒ completion not_applicable, trust degraded via system status', () => {
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
      garmin: { required: false },
    };
    const staleSync = '2026-04-13T10:00:00.000Z'; // 4 days before NOW_AFTERNOON
    const sources = makeSources({
      latestHrvMeasurement: makeMeasurement('hrv_rmssd', 55, staleSync),
      systemStatus: makeSystemStatus({
        sources: [
          makeSource('garmin_connect', { last_sync_at: staleSync }),
          makeSource('hc900_ble', { device_paired: true }),
        ],
      }),
    });
    const vm = deriveTodayViewModel(protocol, sources);

    expect(vm.completion.find((c) => c.kind === 'garmin')!.status).toBe('not_applicable');
    expect(vm.priorityActions.find((a) => a.kind === 'garmin')).toBeUndefined();
    expect(vm.trust.status).toBe('degraded');
    expect(vm.trust.detail.toLowerCase()).toContain('garmin sync stale');
    expect(vm.blockers).toHaveLength(0);
  });
});

// ── State distinctions ──────────────────────────────────────────────────

describe('Today v2 · blocked vs action_needed', () => {
  it('all required-incomplete are blocked ⇒ state=blocked', () => {
    // Protocol: only weight required; scale unpaired
    const protocol: DailyProtocol = {
      date: DATE,
      checkIn: { required: false },
      checkOut: { required: false },
      medication: { required: false },
      temperature: { required: false, minReadings: 0 },
      symptoms: { required: false },
      weight: { required: true },
      garmin: { required: false },
    };
    const sources = makeSources({
      systemStatus: makeSystemStatus({
        sources: [
          makeSource('garmin_connect'),
          makeSource('hc900_ble', { device_paired: false }),
        ],
      }),
    });
    const vm = deriveTodayViewModel(protocol, sources);

    expect(vm.state).toBe('blocked');
    expect(vm.hero.kind).toBe('blocked');
    if (vm.hero.kind === 'blocked') {
      expect(vm.hero.blocker.kind).toBe('weight');
    }
    expect(vm.priorityActions).toHaveLength(0);
  });

  it('blocked item + actionable item ⇒ state=action_needed, blocker still listed', () => {
    const sources = makeSources({
      systemStatus: makeSystemStatus({
        sources: [
          makeSource('garmin_connect'),
          makeSource('hc900_ble', { device_paired: false }),
        ],
      }),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);

    expect(vm.state).toBe('action_needed');
    expect(vm.blockers.find((b) => b.kind === 'weight')).toBeDefined();
    expect(vm.priorityActions.length).toBeGreaterThan(0);
  });
});

// ── Prioritization tie-breaks ────────────────────────────────────────────

describe('Today v2 · priority tie-breaks', () => {
  it('day_integrity outranks improves_trust (check_in before weight)', () => {
    const sources = makeSources({ systemStatus: makeSystemStatus() });
    const actions = prioritizeActions(defaultDailyProtocol(DATE), sources);
    const checkIn = actions.find((a) => a.kind === 'check_in')!;
    const weight = actions.find((a) => a.kind === 'weight')!;
    expect(checkIn.rank).toBeLessThan(weight.rank);
  });

  it('time_sensitive breaks ties between day_integrity actions', () => {
    // check_in past window (time_sensitive) vs medication missing (no window)
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
    };
    const sources = makeSources({
      now: NOW_NIGHT, // past checkIn window (15:00 UTC) and past checkOut (23:00)
      checkpointsToday: [], // morning still missing ⇒ past window
      activeRegimens: [makeRegimen()],
      medicationLogsToday: [],
      systemStatus: makeSystemStatus(),
    });
    const actions = prioritizeActions(protocol, sources);
    const checkIn = actions.find((a) => a.kind === 'check_in')!;
    const medication = actions.find((a) => a.kind === 'medication')!;
    expect(checkIn.priorityDrivers).toContain('time_sensitive');
    expect(medication.priorityDrivers).not.toContain('time_sensitive');
    expect(checkIn.rank).toBeLessThan(medication.rank);
  });

  it('lower cost breaks ties when all other drivers match', () => {
    // garmin sync (0s, improves_trust) vs weight (60s, improves_trust)
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
      checkIn: { required: false },
      checkOut: { required: false },
      medication: { required: false },
      temperature: { required: false, minReadings: 0 },
      symptoms: { required: false },
      weight: { required: true },
      garmin: { required: true },
    };
    const sources = makeSources({ systemStatus: makeSystemStatus() });
    const actions = prioritizeActions(protocol, sources);
    const garmin = actions.find((a) => a.kind === 'garmin')!;
    const weight = actions.find((a) => a.kind === 'weight')!;
    expect(garmin.priorityDrivers).toEqual(weight.priorityDrivers);
    expect(garmin.rank).toBeLessThan(weight.rank);
    expect(garmin.estimatedCostSeconds).toBeLessThan(weight.estimatedCostSeconds);
  });
});

// ── Hero invariants ──────────────────────────────────────────────────────

describe('Today v2 · hero always present', () => {
  const scenarios: Array<[string, () => TodayRawSources, DailyProtocol]> = [
    [
      'ok',
      () => makeSources({
        now: NOW_NIGHT,
        checkpointsToday: [makeCheckpoint('morning'), makeCheckpoint('night')],
        weightToday: [makeMeasurement('weight', 75, `${DATE}T07:00:00.000Z`)],
        garminMetricsToday: [makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`)],
        latestHrvMeasurement: makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`),
        systemStatus: makeSystemStatus(),
      }),
      defaultDailyProtocol(DATE),
    ],
    [
      'action_needed',
      () => makeSources({ systemStatus: makeSystemStatus() }),
      defaultDailyProtocol(DATE),
    ],
    [
      'blocked',
      () => makeSources({
        systemStatus: makeSystemStatus({
          sources: [
            makeSource('garmin_connect'),
            makeSource('hc900_ble', { device_paired: false }),
          ],
        }),
      }),
      {
        date: DATE,
        checkIn: { required: false },
        checkOut: { required: false },
        medication: { required: false },
        temperature: { required: false, minReadings: 0 },
        symptoms: { required: false },
        weight: { required: true },
        garmin: { required: false },
      },
    ],
  ];

  it.each(scenarios)('hero exists for state %s', (_label, mkSources, protocol) => {
    const vm = deriveTodayViewModel(protocol, mkSources());
    expect(vm.hero).toBeDefined();
    expect(['action', 'confirmation', 'blocked']).toContain(vm.hero.kind);
  });
});

// ── Check-in / check-out / symptoms coverage ────────────────────────────

describe('Today v2 · check-in / check-out / symptoms in derivation', () => {
  it('check-in complete when morning checkpoint exists', () => {
    const sources = makeSources({
      checkpointsToday: [makeCheckpoint('morning')],
      systemStatus: makeSystemStatus(),
    });
    const completion = deriveCompletion(defaultDailyProtocol(DATE), sources);
    expect(completion.find((c) => c.kind === 'check_in')!.status).toBe('complete');
  });

  it('check-out candidate only surfaces once window is open', () => {
    const sourcesBefore = makeSources({
      now: NOW_AFTERNOON, // before 23:00 UTC
      systemStatus: makeSystemStatus(),
    });
    const sourcesAfter = makeSources({
      now: NOW_NIGHT, // past 23:00 UTC
      checkpointsToday: [makeCheckpoint('morning')],
      systemStatus: makeSystemStatus(),
    });
    const actionsBefore = prioritizeActions(defaultDailyProtocol(DATE), sourcesBefore);
    const actionsAfter = prioritizeActions(defaultDailyProtocol(DATE), sourcesAfter);
    expect(actionsBefore.find((a) => a.kind === 'check_out')).toBeUndefined();
    expect(actionsAfter.find((a) => a.kind === 'check_out')).toBeDefined();
  });

  it('symptoms always surface as signals even when opt-in', () => {
    const sources = makeSources({
      symptomsActiveToday: [makeSymptom()],
      systemStatus: makeSystemStatus(),
    });
    const vm = deriveTodayViewModel(defaultDailyProtocol(DATE), sources);
    const signal = vm.currentSignals.find((s) => s.kind === 'symptoms');
    expect(signal).toBeDefined();
    expect(signal!.value).toContain('Headache');
    // Opt-in ⇒ symptoms completion is not_applicable, no action.
    expect(vm.completion.find((c) => c.kind === 'symptoms')!.status).toBe('not_applicable');
    expect(vm.priorityActions.find((a) => a.kind === 'symptoms')).toBeUndefined();
  });

  it('symptoms required + no log today ⇒ missing + action', () => {
    const protocol: DailyProtocol = {
      ...defaultDailyProtocol(DATE),
      symptoms: { required: true },
    };
    const sources = makeSources({ systemStatus: makeSystemStatus() });
    const vm = deriveTodayViewModel(protocol, sources);
    expect(vm.completion.find((c) => c.kind === 'symptoms')!.status).toBe('missing');
    expect(vm.priorityActions.find((a) => a.kind === 'symptoms')).toBeDefined();
  });
});

// ── Pure helpers directly ────────────────────────────────────────────────

describe('Today v2 · direct helpers', () => {
  it('deriveSurfaceState returns ok when nothing required is incomplete', () => {
    const completion = deriveCompletion(
      defaultDailyProtocol(DATE),
      makeSources({
        checkpointsToday: [makeCheckpoint('morning'), makeCheckpoint('night')],
        weightToday: [makeMeasurement('weight', 75, `${DATE}T07:00:00.000Z`)],
        garminMetricsToday: [makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`)],
        latestHrvMeasurement: makeMeasurement('hrv_rmssd', 55, `${DATE}T06:00:00.000Z`),
        systemStatus: makeSystemStatus(),
      }),
    );
    expect(deriveSurfaceState(completion, [])).toBe('ok');
  });

  it('deriveBlockers returns unpaired-scale blocker when weight is required', () => {
    const blockers = deriveBlockers(
      defaultDailyProtocol(DATE),
      makeSources({
        systemStatus: makeSystemStatus({
          sources: [
            makeSource('garmin_connect'),
            makeSource('hc900_ble', { device_paired: false }),
          ],
        }),
      }),
    );
    expect(blockers).toHaveLength(1);
    expect(blockers[0].cause).toBe('device_not_paired');
  });

  it('deriveTrust returns unknown when system status is null', () => {
    expect(deriveTrust(makeSources()).status).toBe('unknown');
  });

  it('deriveHero falls back to confirmation when state=ok', () => {
    const hero = deriveHero('ok', [], [], []);
    expect(hero.kind).toBe('confirmation');
  });
});
