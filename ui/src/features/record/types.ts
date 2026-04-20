import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementResponse,
  SymptomLogResponse,
} from '../../api/types';

// ── Raw sources ───────────────────────────────────────────────────────────

export interface RecordRawSources {
  date: string;                       // today YYYY-MM-DD (from todayISO())
  now: string;                        // ISO timestamp (from nowISO())
  windowDays: number;                 // active window; default 30
  checkpoints: DailyCheckpointResponse[];
  symptoms: SymptomLogResponse[];
  // 'temperature' is the only manually-logged measurement in Record B6.
  // Sensor measurements (HRV, RHR) are excluded — they are contextualized
  // in Timeline. Other slugs are reserved for future Record iterations.
  temperature: MeasurementResponse[];
  scaleReading: LatestScaleReading | null; // latest only; no historical log endpoint
  // reserved — requires /medication-logs list endpoint (not yet exposed):
  // medicationLogs: MedicationLogResponse[];
}

// ── Record entry ──────────────────────────────────────────────────────────

// 'temperature' is explicit rather than a generic 'measurement' to make
// B6 scope unambiguous: only manual temperature entries are included.
export type RecordEntryType = 'checkpoint' | 'symptom' | 'temperature' | 'scale';

export interface RecordEntry {
  id: string;
  type: RecordEntryType;
  timestamp: string;      // ISO — primary sort key within a day
  label: string;          // 'Morning check-in' | 'Night check-out' | symptom name | 'Temperature' | 'Scale'
  summary: string;        // 'Mood 7 · Energy 6 · Sleep 5' / 'intensity 4 · active' / '37.2 °C' / '78.4 kg · body fat 18.2%'
  detail: string | null;  // checkpoint notes, or null for all other types
}

// ── Day group ─────────────────────────────────────────────────────────────

export interface RecordDayGroup {
  date: string;           // YYYY-MM-DD (local date)
  label: string;          // 'Apr 18 Fri'
  isToday: boolean;
  entries: RecordEntry[]; // sorted by timestamp desc within the day
  entryCount: number;     // === entries.length (convenience)
}

// ── View model ────────────────────────────────────────────────────────────

// Filter values mirror RecordEntryType plus 'all'.
export type RecordFilter = 'all' | 'checkpoint' | 'symptom' | 'temperature' | 'scale';

export interface RecordViewModel {
  dayGroups: RecordDayGroup[];  // most recent first; days with no visible entries omitted
  totalEntries: number;         // count after applying filter
  windowDays: number;
  activeFilter: RecordFilter;
  isEmpty: boolean;
  // true when the scale reading shown falls before today — signals the UI
  // to display a "last available reading · <date>" caveat.
  scaleReadingIsHistorical: boolean;
}
