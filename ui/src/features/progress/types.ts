import type {
  DailyCheckpointResponse,
  InsightSummary,
  MeasurementResponse,
  MedicationAdherenceResponse,
  SymptomLogResponse,
  SystemStatusResponse,
} from '../../api/types';

// ── Raw inputs ────────────────────────────────────────────────────────────

export interface ProgressRawSources {
  /** YYYY-MM-DD local day the VM is being computed for. */
  date: string;
  /** ISO datetime injected at derivation time; keeps derivation pure. */
  now: string;
  /** Up to 14 days of checkpoints ending today. */
  checkpoints14d: DailyCheckpointResponse[];
  /** Recent symptom logs (up to 50), pre-filtered to the 14-day window. */
  symptoms14d: SymptomLogResponse[];
  medicationAdherence: MedicationAdherenceResponse | null;
  /** hrv_rmssd measurements, last 14 readings (descending measured_at). */
  hrv14d: MeasurementResponse[];
  /** resting_hr measurements, last 14 readings (descending measured_at). */
  rhr14d: MeasurementResponse[];
  summary: InsightSummary | null;
  systemStatus: SystemStatusResponse | null;
}

// ── Shared confidence enum ────────────────────────────────────────────────

/**
 * How much analytical weight each block carries.
 *
 *   sufficient  — enough data; interpretation is meaningful
 *   limited     — some data; trend forming but treat with caution
 *   insufficient — too little data; block shown with caveat only
 */
export type DataConfidence = 'sufficient' | 'limited' | 'insufficient';

// ── Block types ───────────────────────────────────────────────────────────

export interface ConsistencyBlock {
  /**
   * Fraction of 14-day window with at least one morning check-in (0–1).
   * Null when total checkpoints < 3 (cannot compute a meaningful rate).
   */
  checkInRate: number | null;
  /** Fraction of 14-day window with at least one night check-in (0–1). */
  checkOutRate: number | null;
  /**
   * Overall medication adherence fraction (0–1), normalised from the API's
   * 0–100 percentage. Null when no active regimens or all pending first log.
   */
  medicationAdherence: number | null;
  /** Calendar days in the observation window (always 14). */
  windowDays: number;
  dataConfidence: DataConfidence;
  caveat: string | null;
}

export type SignalDirection = 'up' | 'down' | 'stable';

export interface SignalTrend {
  direction: SignalDirection;
  /** Mean of the most recent 7-day window. */
  recentMean: number;
  /** Mean of the prior 7-day window. */
  priorMean: number;
  /** (recentMean - priorMean) / priorMean × 100. Negative = declined. */
  deltaPct: number;
  unit: string;
  recentN: number;
  priorN: number;
}

export interface SignalDirectionBlock {
  /** null when either window has fewer than MIN_SIGNAL_N readings. */
  hrv: SignalTrend | null;
  rhr: SignalTrend | null;
  windowDays: 7;
  dataConfidence: DataConfidence;
  caveat: string | null;
}

/**
 * Direction of reported symptom burden over time.
 *
 *   improving        — fewer logs in recent 7d vs prior 7d, logging consistent
 *   worsening        — more logs in recent 7d vs prior 7d, logging consistent
 *   stable           — delta ≤ SYMPTOM_STABLE_DELTA, logging consistent
 *   unclear          — logging consistency low; cannot distinguish
 *                      "fewer symptoms" from "stopped logging"
 *   insufficient_data — no symptom logs in either window
 */
export type SymptomBurdenDirection =
  | 'improving'
  | 'worsening'
  | 'stable'
  | 'unclear'
  | 'insufficient_data';

export interface ReportedSymptomBurdenBlock {
  recentCount: number;
  priorCount: number;
  direction: SymptomBurdenDirection;
  /** Most frequent symptom slug in the recent window, or null. */
  topSymptom: string | null;
  /**
   * True when check-in rate < LOGGING_CONSISTENCY_THRESHOLD and recent
   * symptom logs < MIN_SYMPTOM_LOGS_FOR_DIRECTION.  When true, direction
   * is capped at 'unclear' — fewer logs may mean stopped logging, not
   * genuine improvement.
   */
  loggingConsistencyLow: boolean;
  caveat: string | null;
}

export interface DataConfidenceBlock {
  /**
   * Operational freshness — are the data pipelines actually running?
   * Derived from SystemSourceStatus.last_sync_at / device_paired.
   */
  freshness: {
    garminOk: boolean;
    scaleOk: boolean;
    overallOk: boolean;
  };
  /**
   * Analytical sufficiency — do we have enough data to interpret each block?
   * Derived from InsightSummary.block_availability and check-in rate.
   */
  analyticalCoverage: {
    /** Count of insight blocks with availability_status === 'ok'. */
    blocksWithData: number;
    totalBlocks: number;
    /** True when check-in rate ≥ LOGGING_CONSISTENCY_THRESHOLD over the window. */
    checkInConsistent: boolean;
  };
  /** Short human-readable summary combining both dimensions. */
  summary: string;
}

// ── Top-level VM ──────────────────────────────────────────────────────────

/**
 * Conservative aggregate over all blocks.
 *
 *   no_data   — nothing loaded or all sources null/empty
 *   limited   — both key blocks insufficient (collecting data)
 *   mixed     — blocks disagree (some sufficient, some not)
 *   sufficient — both key blocks at least limited, ≥1 sufficient
 */
export type ProgressOverallState = 'sufficient' | 'mixed' | 'limited' | 'no_data';

export interface ProgressViewModel {
  overallState: ProgressOverallState;
  /** Short factual headline derived from overallState + worst bottleneck. */
  headline: string;
  consistency: ConsistencyBlock;
  signalDirection: SignalDirectionBlock;
  reportedSymptomBurden: ReportedSymptomBurdenBlock;
  dataConfidence: DataConfidenceBlock;
}
