export interface InsightSummary {
  user_id: string;
  as_of: string;
  overall_adherence_pct: number;
  active_deviations: number;
  current_symptom_burden: number;
  illness_signal: string;
  recovery_status: string;
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
  adherence_pct: number;
}

export interface MedicationAdherenceResponse {
  user_id: string;
  items: MedicationAdherenceItem[];
  overall_adherence_pct: number;
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
