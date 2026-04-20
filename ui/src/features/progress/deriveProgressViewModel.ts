import type { MeasurementResponse, SymptomLogResponse, DailyCheckpointResponse } from '../../api/types';
import type {
  ConsistencyBlock,
  DataConfidence,
  DataConfidenceBlock,
  ProgressOverallState,
  ProgressRawSources,
  ProgressViewModel,
  ReportedSymptomBurdenBlock,
  SignalDirection,
  SignalDirectionBlock,
  SignalTrend,
  SymptomBurdenDirection,
} from './types';

// ── Thresholds (exported for tests) ──────────────────────────────────────

/**
 * Neutral zone for HRV (hrv_rmssd): changes smaller than this percentage
 * are treated as noise, not trend.  HRV is high-variance day-to-day; an
 * 8% shift in the 7d mean-vs-mean comparison is the minimum meaningful delta.
 */
export const SIGNAL_HRV_NEUTRAL_PCT = 8;

/**
 * Neutral zone for resting heart rate: changes smaller than this absolute
 * bpm value are treated as noise.  RHR is more stable than raw HRV; 3 bpm
 * is within typical daily variation.
 */
export const SIGNAL_RHR_NEUTRAL_BPM = 3;

/**
 * Minimum number of readings required in *each* comparison window (recent
 * and prior) to compute a directional trend.  Below this, the trend is null
 * and DataConfidence is 'insufficient'.
 */
export const MIN_SIGNAL_N = 3;

/**
 * Check-in rate threshold (fraction, 0–1).  Below this the user is not
 * logging consistently enough for symptom-burden direction to be meaningful
 * (we cannot distinguish "fewer symptoms" from "stopped logging").
 */
export const LOGGING_CONSISTENCY_THRESHOLD = 0.5;

/**
 * Minimum symptom logs in the recent 7-day window required before we trust
 * the direction signal, when combined with low check-in rate.  If both
 * conditions hold (rate < threshold AND recent logs < this), direction is
 * capped at 'unclear'.
 */
export const MIN_SYMPTOM_LOGS_FOR_DIRECTION = 3;

/**
 * Symptom count delta at or below which the burden is considered stable
 * (i.e., |recentCount - priorCount| ≤ this value).
 */
export const SYMPTOM_STABLE_DELTA = 1;

/** Check-in rate at or above which consistency is 'sufficient'. */
export const CONSISTENCY_SUFFICIENT_THRESHOLD = 0.7;

/** Check-in rate at or above which consistency is 'limited' (below → 'insufficient'). */
export const CONSISTENCY_LIMITED_THRESHOLD = LOGGING_CONSISTENCY_THRESHOLD;

// ── Internal helpers ──────────────────────────────────────────────────────

const MS_DAY = 24 * 60 * 60 * 1000;

function mean(values: number[]): number {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/**
 * Split a measurement array into two non-overlapping windows relative to `now`:
 *   recent — (now - windowDays, now]
 *   prior  — (now - 2*windowDays, now - windowDays]
 *
 * Uses strict `>` / `<=` boundaries so a reading exactly at the cutoff falls
 * into the prior window (not double-counted).
 */
function splitIntoWindows(
  measurements: MeasurementResponse[],
  now: string,
  windowDays: number,
): { recent: MeasurementResponse[]; prior: MeasurementResponse[] } {
  const nowMs = new Date(now).getTime();
  const cutoffRecent = nowMs - windowDays * MS_DAY;
  const cutoffPrior = nowMs - 2 * windowDays * MS_DAY;

  const recent = measurements.filter((m) => {
    const t = new Date(m.measured_at).getTime();
    return t > cutoffRecent && t <= nowMs;
  });
  const prior = measurements.filter((m) => {
    const t = new Date(m.measured_at).getTime();
    return t > cutoffPrior && t <= cutoffRecent;
  });
  return { recent, prior };
}

function splitSymptomsIntoWindows(
  symptoms: SymptomLogResponse[],
  now: string,
  windowDays: number,
): { recent: SymptomLogResponse[]; prior: SymptomLogResponse[] } {
  const nowMs = new Date(now).getTime();
  const cutoffRecent = nowMs - windowDays * MS_DAY;
  const cutoffPrior = nowMs - 2 * windowDays * MS_DAY;

  const recent = symptoms.filter((s) => {
    const t = new Date(s.started_at).getTime();
    return t > cutoffRecent && t <= nowMs;
  });
  const prior = symptoms.filter((s) => {
    const t = new Date(s.started_at).getTime();
    return t > cutoffPrior && t <= cutoffRecent;
  });
  return { recent, prior };
}

/**
 * Derive a single metric trend from pre-split window arrays.
 *
 * Returns null when either window has fewer than MIN_SIGNAL_N readings —
 * this is intentional: we prefer "no answer" over a misleading direction.
 *
 * The `isNeutral` predicate determines whether the observed delta falls
 * inside the metric's neutral zone (returns 'stable' instead of 'up'/'down').
 */
function deriveSignalTrend(
  recent: MeasurementResponse[],
  prior: MeasurementResponse[],
  unit: string,
  isNeutral: (deltaPctAbs: number, deltaAbsAbs: number) => boolean,
): SignalTrend | null {
  if (recent.length < MIN_SIGNAL_N || prior.length < MIN_SIGNAL_N) return null;

  const recentMean = mean(recent.map((m) => Number(m.value_num)));
  const priorMean = mean(prior.map((m) => Number(m.value_num)));

  if (priorMean === 0) return null; // avoid division by zero

  const deltaAbs = recentMean - priorMean;
  const deltaPct = (deltaAbs / priorMean) * 100;

  const direction: SignalDirection = isNeutral(Math.abs(deltaPct), Math.abs(deltaAbs))
    ? 'stable'
    : deltaAbs > 0
      ? 'up'
      : 'down';

  return {
    direction,
    recentMean,
    priorMean,
    deltaPct,
    unit,
    recentN: recent.length,
    priorN: prior.length,
  };
}

function morningDatesSet(checkpoints: DailyCheckpointResponse[]): Set<string> {
  return new Set(
    checkpoints.filter((c) => c.checkpoint_type === 'morning').map((c) => c.checkpoint_date),
  );
}

// ── Block derivation ──────────────────────────────────────────────────────

function deriveConsistency(
  checkpoints14d: DailyCheckpointResponse[],
  adherence: ProgressRawSources['medicationAdherence'],
  windowDays: number,
): ConsistencyBlock {
  const morningDates = morningDatesSet(checkpoints14d);
  const nightDates = new Set(
    checkpoints14d
      .filter((c) => c.checkpoint_type === 'night')
      .map((c) => c.checkpoint_date),
  );

  const totalLogged = morningDates.size + nightDates.size;

  if (totalLogged < 3) {
    return {
      checkInRate: null,
      checkOutRate: null,
      medicationAdherence: null,
      windowDays,
      dataConfidence: 'insufficient',
      caveat: `Only ${totalLogged} check-in/out logs in the last ${windowDays} days — cannot assess consistency yet`,
    };
  }

  const checkInRate = morningDates.size / windowDays;
  const checkOutRate = nightDates.size / windowDays;
  const medicationAdherence =
    adherence?.overall_adherence_pct != null
      ? adherence.overall_adherence_pct / 100
      : null;

  const dataConfidence: DataConfidence =
    checkInRate >= CONSISTENCY_SUFFICIENT_THRESHOLD
      ? 'sufficient'
      : checkInRate >= CONSISTENCY_LIMITED_THRESHOLD
        ? 'limited'
        : 'insufficient';

  const caveat =
    dataConfidence === 'insufficient'
      ? `${morningDates.size}/${windowDays} check-in days — too sparse for reliable consistency`
      : dataConfidence === 'limited'
        ? `${morningDates.size}/${windowDays} check-in days — trend forming`
        : null;

  return { checkInRate, checkOutRate, medicationAdherence, windowDays, dataConfidence, caveat };
}

function deriveSignalDirection(
  hrv14d: MeasurementResponse[],
  rhr14d: MeasurementResponse[],
  now: string,
): SignalDirectionBlock {
  const { recent: hrvRecent, prior: hrvPrior } = splitIntoWindows(hrv14d, now, 7);
  const { recent: rhrRecent, prior: rhrPrior } = splitIntoWindows(rhr14d, now, 7);

  // HRV neutral zone: percentage-based (high-variance metric)
  const hrv = deriveSignalTrend(
    hrvRecent,
    hrvPrior,
    'ms',
    (pctAbs) => pctAbs < SIGNAL_HRV_NEUTRAL_PCT,
  );

  // RHR neutral zone: absolute bpm (more stable metric, absolute threshold is tighter)
  const rhr = deriveSignalTrend(
    rhrRecent,
    rhrPrior,
    'bpm',
    (_pctAbs, absAbs) => absAbs < SIGNAL_RHR_NEUTRAL_BPM,
  );

  const hasBoth = hrv !== null && rhr !== null;
  const hasAny = hrv !== null || rhr !== null;

  const dataConfidence: DataConfidence = hasBoth
    ? 'sufficient'
    : hasAny
      ? 'limited'
      : 'insufficient';

  const caveat = !hasAny
    ? `Need ${MIN_SIGNAL_N}+ readings in each 7-day window — collecting data`
    : !hasBoth
      ? 'Only one of HRV / resting HR has enough readings for this period'
      : null;

  return { hrv, rhr, windowDays: 7, dataConfidence, caveat };
}

function deriveReportedSymptomBurden(
  symptoms14d: SymptomLogResponse[],
  checkpoints14d: DailyCheckpointResponse[],
  now: string,
): ReportedSymptomBurdenBlock {
  const { recent, prior } = splitSymptomsIntoWindows(symptoms14d, now, 7);

  // Derive logging consistency from check-ins (14-day denominator)
  const morningDates = morningDatesSet(checkpoints14d);
  const checkInRate = morningDates.size / 14;
  const loggingConsistencyLow =
    checkInRate < LOGGING_CONSISTENCY_THRESHOLD &&
    recent.length < MIN_SYMPTOM_LOGS_FOR_DIRECTION;

  // Top symptom by frequency in recent window
  const counts: Record<string, number> = {};
  for (const s of recent) {
    const slug = s.symptom_slug ?? 'unknown';
    counts[slug] = (counts[slug] ?? 0) + 1;
  }
  const topSymptom =
    Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0] ?? null;

  // Direction — capped at 'unclear' when logging is too sparse to interpret
  let direction: SymptomBurdenDirection;
  if (recent.length === 0 && prior.length === 0) {
    direction = 'insufficient_data';
  } else if (loggingConsistencyLow) {
    // Cannot distinguish "fewer symptoms" from "stopped logging"
    direction = 'unclear';
  } else {
    const delta = recent.length - prior.length;
    if (Math.abs(delta) <= SYMPTOM_STABLE_DELTA) {
      direction = 'stable';
    } else if (delta < 0) {
      direction = 'improving';
    } else {
      direction = 'worsening';
    }
  }

  const caveat =
    direction === 'unclear'
      ? 'Low logging consistency — cannot distinguish fewer symptoms from fewer logs'
      : direction === 'insufficient_data'
        ? 'No symptom logs recorded in the 14-day window'
        : null;

  return { recentCount: recent.length, priorCount: prior.length, direction, topSymptom, loggingConsistencyLow, caveat };
}

function deriveDataConfidence(
  systemStatus: ProgressRawSources['systemStatus'],
  summary: ProgressRawSources['summary'],
  checkInRate: number | null,
): DataConfidenceBlock {
  // ── Freshness dimension (operational) ─────────────────────────────────
  const garminSource = systemStatus?.sources.find((s) => s.source_slug === 'garmin_connect');
  const scaleSource = systemStatus?.sources.find((s) => s.source_slug === 'hc900_ble');

  const garminOk =
    garminSource != null &&
    garminSource.integration_configured !== false &&
    garminSource.last_run_status !== 'error';
  const scaleOk = scaleSource?.device_paired === true;
  const freshnessOverallOk = garminOk && scaleOk;

  // ── Analytical dimension (sufficiency) ────────────────────────────────
  const ba = summary?.block_availability;
  const blockStatuses = ba
    ? [ba.deviations, ba.illness, ba.recovery, ba.adherence, ba.symptoms]
    : [];
  const blocksWithData = blockStatuses.filter((s) => s === 'ok').length;
  const totalBlocks = blockStatuses.length;
  const checkInConsistent =
    checkInRate !== null && checkInRate >= LOGGING_CONSISTENCY_THRESHOLD;

  // ── Human-readable summary ────────────────────────────────────────────
  let summaryText: string;
  if (!systemStatus && !summary) {
    summaryText = 'System status not available';
  } else {
    const parts: string[] = [];
    if (!freshnessOverallOk) parts.push('pipeline issues detected');
    if (totalBlocks > 0 && blocksWithData < totalBlocks)
      parts.push(`${blocksWithData}/${totalBlocks} analysis blocks with data`);
    if (!checkInConsistent) parts.push('check-in logging below 50%');
    summaryText = parts.length > 0 ? parts.join(' · ') : 'data sources healthy';
  }

  return {
    freshness: { garminOk, scaleOk, overallOk: freshnessOverallOk },
    analyticalCoverage: { blocksWithData, totalBlocks, checkInConsistent },
    summary: summaryText,
  };
}

function deriveOverallState(
  consistency: ConsistencyBlock,
  signal: SignalDirectionBlock,
  sources: ProgressRawSources,
): ProgressOverallState {
  const hasAnySources =
    sources.systemStatus !== null ||
    sources.summary !== null ||
    sources.hrv14d.length > 0 ||
    sources.checkpoints14d.length > 0;

  if (!hasAnySources) return 'no_data';

  // Score the two key analytical blocks (the ones that answer the core questions)
  const scores = [consistency.dataConfidence, signal.dataConfidence].map((c) =>
    c === 'sufficient' ? 2 : c === 'limited' ? 1 : 0,
  );
  const total = scores.reduce((a, b) => a + b, 0);
  const maxTotal = scores.length * 2; // 4

  if (total === maxTotal) return 'sufficient';
  if (total === 0) return 'limited';
  return 'mixed';
}

function deriveHeadline(
  state: ProgressOverallState,
  consistency: ConsistencyBlock,
  signal: SignalDirectionBlock,
  symptom: ReportedSymptomBurdenBlock,
): string {
  if (state === 'no_data') return 'No data yet — start logging to see your progress';
  if (state === 'limited') return 'Collecting data — check back after a few more days of logging';

  const parts: string[] = [];

  if (consistency.checkInRate !== null) {
    parts.push(`${Math.round(consistency.checkInRate * 100)}% check-in rate`);
  }

  const hrvDir = signal.hrv?.direction;
  if (hrvDir === 'up') parts.push('HRV trending up');
  else if (hrvDir === 'down') parts.push('HRV trending down');
  else if (hrvDir === 'stable') parts.push('HRV stable');

  if (symptom.direction === 'improving') parts.push('fewer reported symptoms');
  else if (symptom.direction === 'worsening') parts.push('more reported symptoms');

  return parts.length > 0 ? parts.join(' · ') : 'Data collected — monitoring trends';
}

// ── Public entry point ────────────────────────────────────────────────────

export function deriveProgressViewModel(sources: ProgressRawSources): ProgressViewModel {
  const consistency = deriveConsistency(sources.checkpoints14d, sources.medicationAdherence, 14);
  const signalDirection = deriveSignalDirection(sources.hrv14d, sources.rhr14d, sources.now);
  const reportedSymptomBurden = deriveReportedSymptomBurden(
    sources.symptoms14d,
    sources.checkpoints14d,
    sources.now,
  );
  const dataConfidence = deriveDataConfidence(
    sources.systemStatus,
    sources.summary,
    consistency.checkInRate,
  );
  const overallState = deriveOverallState(consistency, signalDirection, sources);
  const headline = deriveHeadline(overallState, consistency, signalDirection, reportedSymptomBurden);

  return { overallState, headline, consistency, signalDirection, reportedSymptomBurden, dataConfidence };
}
