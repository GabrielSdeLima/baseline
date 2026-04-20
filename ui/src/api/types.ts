// ── Onda 2 availability types ─────────────────────────────────────────────

export type AvailabilityStatus =
  | 'ok'
  | 'no_data'
  | 'no_data_today'
  | 'insufficient_data'
  | 'stale_data'
  | 'partial'
  | 'not_applicable';

export interface DataAvailability {
  availability_status: AvailabilityStatus;
  target_date: string | null;
  has_data_for_target_date: boolean | null;
  latest_measured_at: string | null;
  latest_synced_at: string | null;
  missing_metrics: string[];
  metrics_with_baseline: string[];
  metrics_without_baseline: string[];
  stale_metrics: string[];
}

export interface SummaryBlockAvailability {
  deviations: AvailabilityStatus;
  illness: AvailabilityStatus;
  recovery: AvailabilityStatus;
  adherence: AvailabilityStatus;
  symptoms: AvailabilityStatus;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface InsightSummary {
  user_id: string;
  as_of: string;
  /** null when no active regimens (not_applicable) or all pending. */
  overall_adherence_pct: number | null;
  active_deviations: number;
  current_symptom_burden: number;
  illness_signal: string;
  recovery_status: string;
  block_availability: SummaryBlockAvailability;
  data_availability: DataAvailability | null;
}

export interface MetricDeviation {
  day: string;
  metric_slug: string;
  metric_name: string;
  value: number;
  baseline_avg: number;
  baseline_stddev: number;
  z_score: number;
  delta_abs: number;
  delta_pct: number | null;
}

export interface PhysiologicalDeviationsResponse {
  user_id: string;
  baseline_window_days: number;
  deviation_threshold: number;
  deviations: MetricDeviation[];
  metrics_flagged: number;
  availability_status: AvailabilityStatus;
  data_availability: DataAvailability | null;
}

export interface IllnessSignalDay {
  day: string;
  signal_level: string;
  temp_z: number | null;
  hrv_z: number | null;
  rhr_z: number | null;
  symptom_burden: number;
  energy: number | null;
}

export interface IllnessSignalResponse {
  user_id: string;
  method: string;
  days: IllnessSignalDay[];
  peak_signal: string;
  peak_signal_date: string | null;
}

export interface RecoveryDay {
  day: string;
  status: string;
  hrv_value: number | null;
  hrv_z: number | null;
  hrv_7d_avg: number | null;
  training_load: number | null;
}

export interface RecoveryStatusResponse {
  user_id: string;
  method: string;
  days: RecoveryDay[];
  current_status: string;
}

export interface MedicationAdherenceItem {
  medication_name: string;
  frequency: string;
  taken: number;
  skipped: number;
  delayed: number;
  total: number;
  /** null when item_status is pending_first_log. */
  adherence_pct: number | null;
  item_status: 'ok' | 'pending_first_log';
}

export interface MedicationAdherenceResponse {
  user_id: string;
  items: MedicationAdherenceItem[];
  /** null when not_applicable or all items are pending_first_log. */
  overall_adherence_pct: number | null;
  availability_status: AvailabilityStatus;
}

export interface MedicationDefinitionResponse {
  id: number;
  name: string;
  active_ingredient: string | null;
  dosage_form: string | null;
  description: string | null;
  created_at: string;
}

export interface MeasurementResponse {
  id: string;
  user_id: string;
  metric_type_slug: string | null;
  metric_type_name: string | null;
  source_slug: string | null;
  // FIXME: backend serializes Decimal as a JSON string (e.g. "78.12"), but this
  // field is typed as number. Consumers must coerce with Number(...) before
  // calling number methods (toFixed, arithmetic). Normalize at the fetch
  // boundary — parse in fetchMeasurements (api/client.ts) so downstream code
  // can trust the type. Tracked as follow-up after checkpoints 500 diagnosis
  // (2026-04-18); deferred to avoid scope creep.
  value_num: number;
  unit: string;
  measured_at: string;
  aggregation_level: string;
}

export interface MeasurementList {
  items: MeasurementResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface DailyCheckpointResponse {
  id: string;
  user_id: string;
  checkpoint_type: string;
  checkpoint_date: string;
  checkpoint_at: string;
  mood: number | null;
  energy: number | null;
  sleep_quality: number | null;
  body_state_score: number | null;
  notes: string | null;
}

export interface DailyCheckpointList {
  items: DailyCheckpointResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface SymptomLogResponse {
  id: string;
  user_id: string;
  symptom_slug: string | null;
  symptom_name: string | null;
  intensity: number;
  status: string;
  started_at: string;
}

export interface SymptomLogList {
  items: SymptomLogResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface MedicationRegimenResponse {
  id: string;
  user_id: string;
  medication_id: number;
  medication_name: string | null;
  dosage_amount: number;
  dosage_unit: string;
  frequency: string;
  instructions: string | null;
  prescribed_by: string | null;
  started_at: string;
  ended_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MedicationRegimenList {
  items: MedicationRegimenResponse[];
  total: number;
  offset: number;
  limit: number;
}

// ── Medication logs ───────────────────────────────────────────────────────

export interface MedicationLogResponse {
  id: string;
  user_id: string;
  regimen_id: string;
  status: string;
  scheduled_at: string;
  taken_at: string | null;
  dosage_amount: number | null;
  dosage_unit: string | null;
  notes: string | null;
  recorded_at: string;
  ingested_at: string;
}

export interface MedicationLogList {
  items: MedicationLogResponse[];
  total: number;
  offset: number;
  limit: number;
}

// ── Onda 3 B1 System Status ───────────────────────────────────────────────

export type AgentStatus = 'active' | 'stale' | 'unknown';

export interface SystemSourceStatus {
  source_slug: string;
  integration_configured: boolean;
  device_paired: boolean | null;
  last_sync_at: string | null;
  last_advanced_at: string | null;
  last_run_status: string | null;
  last_run_at: string | null;
}

export interface SystemAgentSummary {
  agent_type: string;
  display_name: string | null;
  status: AgentStatus;
  last_seen_at: string | null;
}

export interface SystemStatusResponse {
  user_id: string;
  sources: SystemSourceStatus[];
  agents: SystemAgentSummary[];
  as_of: string;
}

// ─────────────────────────────────────────────────────────────────────────────

export type GarminSyncStatus =
  | 'completed'
  | 'no_new_data'
  | 'failed'
  | 'already_running';

export interface GarminSyncResponse {
  status: GarminSyncStatus;
  run_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────

export type ScaleReadingStatus = 'full_reading' | 'weight_only' | 'never_measured';

export interface ScaleMetric {
  slug: string;
  /** Stringified Decimal from the API — parse with Number(m.value). */
  value: string;
  unit: string;
  is_derived: boolean;
}

export interface LatestScaleReading {
  status: ScaleReadingStatus;
  measured_at: string | null;
  raw_payload_id: string | null;
  decoder_version: string | null;
  has_impedance: boolean;
  metrics: Record<string, ScaleMetric>;
}
