import type {
  DailyCheckpointResponse,
  SymptomLogResponse,
  SystemSourceStatus,
} from '../../api/types';
import type {
  ActionPriorityDriver,
  CompletionStatus,
  DailyProtocol,
  ProtocolKind,
  TodayActionVM,
  TodayBlockerVM,
  TodayCompletionItemVM,
  TodayHero,
  TodayRawSources,
  TodaySignalVM,
  TodaySurfaceState,
  TodayTrustVM,
  TodayViewModel,
  TrustStatus,
} from './types';

// ── Time / freshness helpers ──────────────────────────────────────────────

const MS_DAY = 24 * 60 * 60 * 1000;
const GARMIN_STALE_MS = 48 * 60 * 60 * 1000;

function msBetween(isoA: string, isoB: string): number {
  return new Date(isoA).getTime() - new Date(isoB).getTime();
}

/**
 * True if `now` ≥ the boundary on `date` expressed as UTC HH:MM.
 * v1: boundaries are UTC. Full per-user timezone support is a follow-up;
 * defaults in `defaultDailyProtocol` are tuned for America/Sao_Paulo (BRT).
 */
function isAfterUtcTime(now: string, date: string, boundaryHHMM: string): boolean {
  const [bh, bm] = boundaryHHMM.split(':').map(Number);
  const y = Number(date.slice(0, 4));
  const mo = Number(date.slice(5, 7)) - 1;
  const d = Number(date.slice(8, 10));
  const boundary = Date.UTC(y, mo, d, bh, bm, 0, 0);
  return new Date(now).getTime() >= boundary;
}

function findSource(sources: TodayRawSources, slug: string): SystemSourceStatus | undefined {
  return sources.systemStatus?.sources.find((s) => s.source_slug === slug);
}

// ── Per-kind derivation ───────────────────────────────────────────────────

interface KindResult {
  completion: TodayCompletionItemVM;
  blocker?: TodayBlockerVM;
  signal?: TodaySignalVM;
  /** Candidate action before ranking; undefined when nothing is actionable. */
  candidate?: ActionCandidate;
}

interface ActionCandidate {
  kind: ProtocolKind;
  label: string;
  reason: string;
  drivers: ActionPriorityDriver[];
  timeSensitive: boolean;
  costSeconds: number;
}

function derivCheckIn(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.checkIn;
  const logged = sources.checkpointsToday.find((c) => c.checkpoint_type === 'morning');

  if (!cfg.required) {
    return { completion: base('check_in', false, 'not_applicable', 'not in today\'s protocol') };
  }
  if (logged) {
    return {
      completion: base('check_in', true, 'complete', detailFromCheckpoint(logged)),
    };
  }
  const past = cfg.windowEnd ? isAfterUtcTime(sources.now, sources.date, cfg.windowEnd) : false;
  const drivers: ActionPriorityDriver[] = ['day_integrity'];
  if (past) drivers.push('time_sensitive');
  drivers.push('low_cost');
  return {
    completion: base('check_in', true, 'missing', past ? 'window elapsed without log' : 'morning log pending'),
    candidate: {
      kind: 'check_in',
      label: 'Morning check-in',
      reason: past ? 'morning window elapsed' : 'morning log pending',
      drivers,
      timeSensitive: past,
      costSeconds: 30,
    },
  };
}

function derivCheckOut(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.checkOut;
  const logged = sources.checkpointsToday.find((c) => c.checkpoint_type === 'night');

  if (!cfg.required) {
    return { completion: base('check_out', false, 'not_applicable', 'not in today\'s protocol') };
  }
  if (logged) {
    return {
      completion: base('check_out', true, 'complete', detailFromCheckpoint(logged)),
    };
  }
  const windowOpen = cfg.windowStart ? isAfterUtcTime(sources.now, sources.date, cfg.windowStart) : true;
  const drivers: ActionPriorityDriver[] = ['day_integrity'];
  if (windowOpen) drivers.push('time_sensitive');
  drivers.push('low_cost');
  return {
    completion: base('check_out', true, 'missing', windowOpen ? 'night log pending' : 'night window not open yet'),
    candidate: windowOpen
      ? {
          kind: 'check_out',
          label: 'Night check-out',
          reason: 'night window open',
          drivers,
          timeSensitive: true,
          costSeconds: 30,
        }
      : undefined,
  };
}

function derivMedication(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.medication;
  const { activeRegimens, medicationLogsToday } = sources;

  if (activeRegimens.length === 0) {
    return { completion: base('medication', false, 'not_applicable', 'no active regimens') };
  }
  if (!cfg.required) {
    return { completion: base('medication', false, 'not_applicable', 'not required today') };
  }

  const total = activeRegimens.length;
  // Any log today (taken, skipped, delayed) means the user consciously handled that regimen.
  const loggedIds = new Set(medicationLogsToday.map((l) => l.regimen_id));
  const loggedCount = activeRegimens.filter((r) => loggedIds.has(r.id)).length;

  let status: CompletionStatus;
  let detail: string;

  if (loggedCount === 0) {
    status = 'missing';
    detail = `${total} regimen${total > 1 ? 's' : ''} — no dose logged today`;
  } else if (loggedCount < total) {
    status = 'partial';
    detail = `${loggedCount} of ${total} regimens logged today`;
  } else {
    status = 'complete';
    detail = `${total} regimen${total > 1 ? 's' : ''} logged today`;
  }

  const candidate: ActionCandidate | undefined =
    status !== 'complete'
      ? {
          kind: 'medication',
          label: loggedCount === 0 ? 'Log today\'s meds' : 'Confirm today\'s doses',
          reason: detail,
          drivers: ['day_integrity', 'low_cost'],
          timeSensitive: false,
          costSeconds: 15,
        }
      : undefined;

  return {
    completion: base('medication', true, status, detail),
    candidate,
  };
}

function derivTemperature(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.temperature;
  const readings = sources.temperatureToday.length;

  if (!cfg.required) {
    const signal = buildTemperatureSignal(sources);
    return {
      completion: base('temperature', false, 'not_applicable', 'not required today'),
      signal,
    };
  }

  const signal = buildTemperatureSignal(sources);

  if (readings >= cfg.minReadings) {
    return {
      completion: base(
        'temperature',
        true,
        'complete',
        `${readings} reading${readings > 1 ? 's' : ''} logged`,
      ),
      signal,
    };
  }

  const symptomActive = sources.symptomsActiveToday.length > 0;
  const drivers: ActionPriorityDriver[] = symptomActive
    ? ['unblocks_others', 'improves_trust', 'low_cost']
    : ['improves_trust', 'low_cost'];

  const status: CompletionStatus = readings > 0 ? 'partial' : 'missing';
  const detail =
    readings > 0
      ? `${readings} of ${cfg.minReadings} required readings`
      : `${cfg.minReadings} reading${cfg.minReadings > 1 ? 's' : ''} required`;

  return {
    completion: base('temperature', true, status, detail),
    signal,
    candidate: {
      kind: 'temperature',
      label: 'Log body temperature',
      reason: symptomActive ? 'symptom active — baseline needs today\'s temp' : 'improves illness signal confidence',
      drivers,
      timeSensitive: false,
      costSeconds: 15,
    },
  };
}

function derivSymptoms(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.symptoms;
  const active = sources.symptomsActiveToday;

  const signal: TodaySignalVM | undefined =
    active.length > 0
      ? {
          id: 'signal:symptoms',
          kind: 'symptoms',
          label: 'Active symptoms',
          value: formatSymptomSummary(active),
          measuredAt: active[0]?.started_at ?? null,
          trust: 'ok',
        }
      : undefined;

  if (!cfg.required) {
    return {
      completion: base('symptoms', false, 'not_applicable', 'opt-in; log when relevant'),
      signal,
    };
  }

  // When required, we treat "no entry today" as missing. A confirm-no-symptom
  // flow would require a dedicated endpoint; until then, stay honest.
  const logged = active.length > 0;
  return {
    completion: base(
      'symptoms',
      true,
      logged ? 'complete' : 'missing',
      logged ? `${active.length} logged` : 'no entry today',
    ),
    signal,
    candidate: logged
      ? undefined
      : {
          kind: 'symptoms',
          label: 'Log symptoms or confirm none',
          reason: 'required by today\'s protocol',
          drivers: ['improves_trust', 'low_cost'],
          timeSensitive: false,
          costSeconds: 30,
        },
  };
}

function derivWeight(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.weight;
  const todayWeight = sources.weightToday[0] ?? null;
  const scale = findSource(sources, 'hc900_ble');
  const scaleBlocked = !!scale && scale.device_paired === false;

  const signal = buildWeightSignal(sources);

  if (!cfg.required) {
    return {
      completion: base('weight', false, 'not_applicable', 'not required today'),
      signal,
    };
  }

  if (todayWeight) {
    return {
      completion: base('weight', true, 'complete', `${Number(todayWeight.value_num).toFixed(2)} ${todayWeight.unit} today`),
      signal,
    };
  }

  if (scaleBlocked) {
    return {
      completion: base('weight', true, 'blocked', 'scale not paired'),
      signal,
      blocker: {
        id: 'blocker:weight:device_not_paired',
        kind: 'weight',
        affects: ['weight'],
        cause: 'device_not_paired',
        message: 'HC900 scale not paired',
        resolutionHint: 'Pair a scale in Settings',
        resolutionSurface: 'Settings',
      },
    };
  }

  return {
    completion: base('weight', true, 'missing', 'no weight logged today'),
    signal,
    candidate: {
      kind: 'weight',
      label: 'Weigh in',
      reason: 'daily baseline needs today\'s weight',
      drivers: ['improves_trust'],
      timeSensitive: false,
      costSeconds: 60,
    },
  };
}

function derivGarmin(protocol: DailyProtocol, sources: TodayRawSources): KindResult {
  const cfg = protocol.garmin;
  const garmin = findSource(sources, 'garmin_connect');
  const garminNotConfigured = !!garmin && garmin.integration_configured === false;

  const hrvTodayExists = sources.garminMetricsToday.some((m) => m.metric_type_slug === 'hrv_rmssd');
  const anyGarminToday = sources.garminMetricsToday.length > 0;
  const staleMs =
    sources.latestHrvMeasurement && sources.latestHrvMeasurement.measured_at
      ? msBetween(sources.now, sources.latestHrvMeasurement.measured_at)
      : null;

  const signal = buildGarminSignal(sources);

  if (!cfg.required) {
    return {
      completion: base('garmin', false, 'not_applicable', 'not required today'),
      signal,
    };
  }

  if (garminNotConfigured) {
    return {
      completion: base('garmin', true, 'blocked', 'Garmin integration not configured'),
      signal,
      blocker: {
        id: 'blocker:garmin:not_configured',
        kind: 'garmin',
        affects: ['garmin'],
        cause: 'not_configured',
        message: 'Garmin integration not configured',
        resolutionHint: 'Connect Garmin in Settings',
        resolutionSurface: 'Settings',
      },
    };
  }

  if (hrvTodayExists) {
    return { completion: base('garmin', true, 'complete', 'HRV received for today'), signal };
  }

  if (anyGarminToday) {
    return {
      completion: base('garmin', true, 'partial', 'some Garmin metrics today, HRV missing'),
      signal,
      candidate: {
        kind: 'garmin',
        label: 'Sync Garmin watch',
        reason: 'HRV for today not received yet',
        drivers: ['improves_trust'],
        timeSensitive: false,
        costSeconds: 0,
      },
    };
  }

  // Nothing today. Distinguish stale-sync (actionable sync) from no-data-ever.
  const status: CompletionStatus = 'missing';
  const staleDetail =
    staleMs != null ? `last HRV ${Math.floor(staleMs / MS_DAY)}d ago` : 'no HRV on record';
  return {
    completion: base('garmin', true, status, staleDetail),
    signal,
    candidate: {
      kind: 'garmin',
      label: 'Sync Garmin watch',
      reason: staleDetail,
      drivers: ['improves_trust'],
      timeSensitive: false,
      costSeconds: 0,
    },
  };
}

// ── Signal builders ───────────────────────────────────────────────────────

function buildTemperatureSignal(sources: TodayRawSources): TodaySignalVM | undefined {
  const latest = sources.temperatureToday[0];
  if (!latest) return undefined;
  return {
    id: 'signal:temperature',
    kind: 'temperature',
    label: 'Body temperature',
    value: `${latest.value_num} ${latest.unit}`,
    measuredAt: latest.measured_at,
    trust: 'ok',
  };
}

function buildWeightSignal(sources: TodayRawSources): TodaySignalVM | undefined {
  const today = sources.weightToday[0];
  if (today) {
    return {
      id: 'signal:weight',
      kind: 'weight',
      label: 'Weight',
      value: `${today.value_num} ${today.unit}`,
      measuredAt: today.measured_at,
      trust: 'ok',
    };
  }
  const latest = sources.latestScaleReading;
  if (latest && latest.measured_at && latest.metrics.weight) {
    return {
      id: 'signal:weight',
      kind: 'weight',
      label: 'Last weight',
      value: `${latest.metrics.weight.value} ${latest.metrics.weight.unit}`,
      measuredAt: latest.measured_at,
      trust: 'degraded',
    };
  }
  return undefined;
}

function buildGarminSignal(sources: TodayRawSources): TodaySignalVM | undefined {
  const hrv = sources.latestHrvMeasurement;
  if (!hrv) return undefined;
  const staleDays = msBetween(sources.now, hrv.measured_at) / MS_DAY;
  const trust: TrustStatus = staleDays <= 1 ? 'ok' : staleDays <= 3 ? 'degraded' : 'degraded';
  return {
    id: 'signal:garmin_hrv',
    kind: 'garmin',
    label: 'HRV (RMSSD)',
    value: `${Math.round(hrv.value_num)} ${hrv.unit}`,
    measuredAt: hrv.measured_at,
    trust,
  };
}

// ── Primitives ────────────────────────────────────────────────────────────

function base(
  kind: ProtocolKind,
  required: boolean,
  status: CompletionStatus,
  detail: string,
): TodayCompletionItemVM {
  return { kind, required, status, detail };
}

function detailFromCheckpoint(c: DailyCheckpointResponse): string {
  const hhmm = c.checkpoint_at?.slice(11, 16);
  return hhmm ? `logged ${hhmm}` : 'logged';
}

function formatSymptomSummary(active: SymptomLogResponse[]): string {
  if (active.length === 1) {
    return active[0].symptom_name ?? active[0].symptom_slug ?? 'symptom';
  }
  return `${active.length} active`;
}

// ── Public derivation steps ───────────────────────────────────────────────

/** Collect per-kind results once so downstream helpers share a single pass. */
function deriveAll(protocol: DailyProtocol, sources: TodayRawSources): Record<ProtocolKind, KindResult> {
  return {
    check_in: derivCheckIn(protocol, sources),
    check_out: derivCheckOut(protocol, sources),
    medication: derivMedication(protocol, sources),
    temperature: derivTemperature(protocol, sources),
    symptoms: derivSymptoms(protocol, sources),
    weight: derivWeight(protocol, sources),
    garmin: derivGarmin(protocol, sources),
  };
}

export function deriveCompletion(
  protocol: DailyProtocol,
  sources: TodayRawSources,
): TodayCompletionItemVM[] {
  const all = deriveAll(protocol, sources);
  return ([
    'check_in',
    'check_out',
    'medication',
    'temperature',
    'symptoms',
    'weight',
    'garmin',
  ] as const).map((k) => all[k].completion);
}

export function deriveBlockers(
  protocol: DailyProtocol,
  sources: TodayRawSources,
): TodayBlockerVM[] {
  const all = deriveAll(protocol, sources);
  const blockers: TodayBlockerVM[] = [];
  for (const k of ['weight', 'garmin', 'check_in', 'check_out', 'medication', 'temperature', 'symptoms'] as const) {
    const b = all[k].blocker;
    if (b) blockers.push(b);
  }
  return blockers;
}

export function prioritizeActions(
  protocol: DailyProtocol,
  sources: TodayRawSources,
): TodayActionVM[] {
  const all = deriveAll(protocol, sources);
  const candidates: ActionCandidate[] = [];
  for (const k of ['check_in', 'check_out', 'medication', 'temperature', 'weight', 'garmin', 'symptoms'] as const) {
    const c = all[k].candidate;
    if (c) candidates.push(c);
  }

  const sorted = [...candidates].sort((a, b) => {
    const drivers: ActionPriorityDriver[] = [
      'day_integrity',
      'time_sensitive',
      'unblocks_others',
      'improves_trust',
    ];
    for (const d of drivers) {
      const av = a.drivers.includes(d) ? 1 : 0;
      const bv = b.drivers.includes(d) ? 1 : 0;
      if (av !== bv) return bv - av;
    }
    return a.costSeconds - b.costSeconds;
  });

  return sorted.map<TodayActionVM>((c, i) => ({
    id: `action:${c.kind}`,
    kind: c.kind,
    label: c.label,
    reason: c.reason,
    rank: i,
    priorityDrivers: c.drivers,
    timeSensitive: c.timeSensitive,
    estimatedCostSeconds: c.costSeconds,
  }));
}

export function deriveSurfaceState(
  completion: TodayCompletionItemVM[],
  actions: TodayActionVM[],
): TodaySurfaceState {
  const requiredIncomplete = completion.filter(
    (c) => c.required && c.status !== 'complete' && c.status !== 'not_applicable',
  );
  if (requiredIncomplete.length === 0) return 'ok';
  if (actions.length === 0) return 'blocked';
  return 'action_needed';
}

export function deriveTrust(sources: TodayRawSources): TodayTrustVM {
  const systemStatus = sources.systemStatus;
  if (!systemStatus) return { status: 'unknown', detail: 'system status not loaded' };

  const issues: string[] = [];
  const garmin = findSource(sources, 'garmin_connect');
  const scale = findSource(sources, 'hc900_ble');

  if (garmin) {
    if (garmin.integration_configured === false) {
      issues.push('Garmin not configured');
    } else {
      // Prefer the cursor's last_sync_at; fall back to the most recent HRV
      // measurement when the cursor hasn't been written yet (e.g. data arrived
      // via the scheduler before the cursor was seeded, or after a manual sync
      // that didn't advance the cursor).
      const syncProxy =
        garmin.last_sync_at ?? garmin.last_advanced_at ?? sources.latestHrvMeasurement?.measured_at ?? null;
      if (!syncProxy) {
        issues.push('Garmin never synced');
      } else if (msBetween(sources.now, syncProxy) > GARMIN_STALE_MS) {
        issues.push('Garmin sync stale');
      }
    }
  }

  if (scale && scale.device_paired === false) {
    issues.push('HC900 scale not paired');
  }

  if (issues.length === 0) {
    return { status: 'ok', detail: 'all sources fresh' };
  }
  return { status: 'degraded', detail: issues.join('; ') };
}

export function deriveHero(
  state: TodaySurfaceState,
  actions: TodayActionVM[],
  blockers: TodayBlockerVM[],
  signals: TodaySignalVM[],
): TodayHero {
  if (state === 'action_needed' && actions.length > 0) {
    return { kind: 'action', action: actions[0] };
  }
  if (state === 'blocked' && blockers.length > 0) {
    return { kind: 'blocked', blocker: blockers[0] };
  }
  // ok — or degenerate states where we still need a hero
  const supporting = signals.find((s) => s.kind === 'garmin') ?? signals[0];
  if (state === 'blocked' && blockers.length === 0) {
    // unreachable by construction, but keep hero contract honest
    return { kind: 'confirmation', message: 'Nothing to act on', supportingSignal: supporting };
  }
  return {
    kind: 'confirmation',
    message: 'Day on track',
    supportingSignal: supporting,
  };
}

// ── Orchestrator ──────────────────────────────────────────────────────────

export function deriveTodayViewModel(
  protocol: DailyProtocol,
  sources: TodayRawSources,
): TodayViewModel {
  const all = deriveAll(protocol, sources);

  const completion = (['check_in', 'check_out', 'medication', 'temperature', 'symptoms', 'weight', 'garmin'] as const)
    .map((k) => all[k].completion);

  const blockers: TodayBlockerVM[] = [];
  for (const k of ['weight', 'garmin', 'check_in', 'check_out', 'medication', 'temperature', 'symptoms'] as const) {
    const b = all[k].blocker;
    if (b) blockers.push(b);
  }

  const signals: TodaySignalVM[] = [];
  for (const k of ['weight', 'temperature', 'garmin', 'symptoms', 'check_in', 'check_out', 'medication'] as const) {
    const s = all[k].signal;
    if (s) signals.push(s);
  }

  const priorityActions = prioritizeActions(protocol, sources);
  const state = deriveSurfaceState(completion, priorityActions);
  const trust = deriveTrust(sources);
  const hero = deriveHero(state, priorityActions, blockers, signals);

  const headline = buildHeadline(state, priorityActions, blockers);
  const subheadline = buildSubheadline(state, completion, priorityActions, blockers);

  return {
    date: sources.date,
    state,
    headline,
    subheadline,
    hero,
    priorityActions,
    completion,
    currentSignals: signals,
    blockers,
    trust,
  };
}

function buildHeadline(
  state: TodaySurfaceState,
  actions: TodayActionVM[],
  blockers: TodayBlockerVM[],
): string {
  if (state === 'ok') return 'Day on track';
  if (state === 'blocked') {
    return blockers[0]?.message ?? 'Blocked';
  }
  const n = actions.length;
  return `${n} thing${n > 1 ? 's' : ''} left today`;
}

function buildSubheadline(
  state: TodaySurfaceState,
  completion: TodayCompletionItemVM[],
  actions: TodayActionVM[],
  blockers: TodayBlockerVM[],
): string | undefined {
  if (state === 'ok') {
    const done = completion.filter((c) => c.status === 'complete').map((c) => c.kind.replace('_', ' '));
    return done.length > 0 ? done.join(' · ') : undefined;
  }
  if (state === 'blocked') {
    return blockers[0]?.resolutionHint;
  }
  if (actions.length === 0) return undefined;
  return actions.slice(0, 3).map((a) => a.label).join(' · ');
}
