import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementResponse,
  MedicationLogResponse,
  MedicationRegimenResponse,
  SymptomLogResponse,
  SystemStatusResponse,
} from '../../api/types';

// ── Protocol ──────────────────────────────────────────────────────────────

export type ProtocolKind =
  | 'check_in'
  | 'check_out'
  | 'medication'
  | 'temperature'
  | 'symptoms'
  | 'weight'
  | 'garmin';

export const PROTOCOL_KINDS: readonly ProtocolKind[] = [
  'check_in',
  'check_out',
  'medication',
  'temperature',
  'symptoms',
  'weight',
  'garmin',
] as const;

export interface ProtocolItemConfig {
  required: boolean;
}

export interface TimedProtocolItemConfig extends ProtocolItemConfig {
  /**
   * HH:MM in UTC, 24h. Absent = no explicit window.
   * v1 limitation: boundaries are always UTC. Default values are tuned
   * for America/Sao_Paulo (BRT, UTC-3); per-user timezone is a follow-up.
   */
  windowEnd?: string;
  windowStart?: string;
}

export interface TemperatureProtocolConfig extends ProtocolItemConfig {
  minReadings: number;
}

export interface DailyProtocol {
  date: string;
  checkIn: TimedProtocolItemConfig;
  checkOut: TimedProtocolItemConfig;
  medication: ProtocolItemConfig;
  temperature: TemperatureProtocolConfig;
  symptoms: ProtocolItemConfig;
  weight: ProtocolItemConfig;
  garmin: ProtocolItemConfig;
}

/**
 * Safe default used until a backend-driven protocol exists.
 * Windows encoded in UTC; 15:00 UTC ≈ 12:00 BRT, 23:00 UTC ≈ 20:00 BRT.
 */
export function defaultDailyProtocol(date: string): DailyProtocol {
  return {
    date,
    checkIn: { required: true, windowEnd: '15:00' },
    checkOut: { required: true, windowStart: '23:00' },
    medication: { required: true },
    temperature: { required: false, minReadings: 1 },
    symptoms: { required: false },
    weight: { required: true },
    garmin: { required: true },
  };
}

// ── Raw sources ───────────────────────────────────────────────────────────

export interface TodayRawSources {
  /** YYYY-MM-DD local day the VM is being computed for. */
  date: string;
  /** ISO datetime injected at derivation time; keeps derivation pure. */
  now: string;
  checkpointsToday: DailyCheckpointResponse[];
  symptomsActiveToday: SymptomLogResponse[];
  temperatureToday: MeasurementResponse[];
  weightToday: MeasurementResponse[];
  latestScaleReading: LatestScaleReading | null;
  /** Garmin-derived daily metrics measured today. */
  garminMetricsToday: MeasurementResponse[];
  /** Most recent HRV measurement irrespective of date — freshness probe. */
  latestHrvMeasurement: MeasurementResponse | null;
  /** Medication logs for today (filtered by UTC date at the API level). */
  medicationLogsToday: MedicationLogResponse[];
  activeRegimens: MedicationRegimenResponse[];
  systemStatus: SystemStatusResponse | null;
}

// ── View model ────────────────────────────────────────────────────────────

export type TodaySurfaceState = 'ok' | 'action_needed' | 'blocked';

export type CompletionStatus =
  | 'complete'
  | 'partial'
  | 'missing'
  | 'blocked'
  | 'not_applicable';

export type TrustStatus = 'ok' | 'degraded' | 'unknown';

export type BlockerCause =
  | 'source_unavailable'
  | 'device_not_paired'
  | 'sync_stale'
  | 'no_data'
  | 'not_configured';

export type BlockerResolutionSurface = 'system' | 'settings' | 'record';

/** Auditable reason why an action sits at a given rank. Not a score. */
export type ActionPriorityDriver =
  | 'day_integrity'
  | 'time_sensitive'
  | 'unblocks_others'
  | 'improves_trust'
  | 'low_cost';

export interface TodayActionVM {
  id: string;
  kind: ProtocolKind;
  label: string;
  reason: string;
  /** Position in the sorted list (0 = highest). Not a weighted score. */
  rank: number;
  priorityDrivers: ActionPriorityDriver[];
  timeSensitive: boolean;
  estimatedCostSeconds: number;
}

export interface TodayCompletionItemVM {
  kind: ProtocolKind;
  required: boolean;
  status: CompletionStatus;
  detail: string;
}

export interface TodaySignalVM {
  id: string;
  kind: ProtocolKind;
  label: string;
  value: string;
  measuredAt: string | null;
  trust: TrustStatus;
}

export interface TodayBlockerVM {
  id: string;
  kind: ProtocolKind;
  affects: ProtocolKind[];
  cause: BlockerCause;
  message: string;
  resolutionHint: string;
  resolutionSurface: BlockerResolutionSurface;
}

export type TodayHero =
  | { kind: 'action'; action: TodayActionVM }
  | { kind: 'confirmation'; message: string; supportingSignal?: TodaySignalVM }
  | { kind: 'blocked'; blocker: TodayBlockerVM };

export interface TodayTrustVM {
  status: TrustStatus;
  detail: string;
}

export interface TodayViewModel {
  date: string;
  state: TodaySurfaceState;
  headline: string;
  subheadline?: string;
  hero: TodayHero;
  priorityActions: TodayActionVM[];
  completion: TodayCompletionItemVM[];
  currentSignals: TodaySignalVM[];
  blockers: TodayBlockerVM[];
  trust: TodayTrustVM;
}
