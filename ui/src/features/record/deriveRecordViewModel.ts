import { format } from 'date-fns';
import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementResponse,
  SymptomLogResponse,
} from '../../api/types';
import type {
  RecordDayGroup,
  RecordEntry,
  RecordFilter,
  RecordRawSources,
  RecordViewModel,
} from './types';

// ── Date helpers ──────────────────────────────────────────────────────────

/**
 * Convert a UTC ISO timestamp to the LOCAL calendar date (YYYY-MM-DD).
 *
 * Record groups entries by the day the user experienced them — which is their
 * LOCAL date, not the UTC date. A symptom logged at 23:45 local should appear
 * under that local day, not the following UTC day.
 *
 * Limitation: `sources.date` (from `todayISO()`) is UTC-sliced, so at UTC
 * midnight boundaries the `isToday` comparison may be off by one day. This is
 * the same temporary imprecision used throughout the app (see subDays in
 * useProgressSources). Acceptable for a single-timezone personal health tool.
 */
export function localDateKey(isoTimestamp: string): string {
  const d = new Date(isoTimestamp);
  return (
    d.getFullYear() +
    '-' +
    String(d.getMonth() + 1).padStart(2, '0') +
    '-' +
    String(d.getDate()).padStart(2, '0')
  );
}

/**
 * Subtract n calendar days from dateStr (YYYY-MM-DD), returning YYYY-MM-DD.
 * Appends 'T00:00:00' (no 'Z') so JS parses it as LOCAL midnight — same
 * convention as useProgressSources.subDays.
 */
export function localDateSubDays(dateStr: string, n: number): string {
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Format a YYYY-MM-DD date string as 'Apr 18 Fri' using a local Date constructor
 *  to avoid date-fns parseISO treating the bare date as UTC midnight. */
function formatDayLabel(dateStr: string): string {
  const [y, m, d] = dateStr.split('-').map(Number);
  return format(new Date(y, m - 1, d), 'MMM d EEE');
}

// ── Entry builders ────────────────────────────────────────────────────────

function buildCheckpointEntry(cp: DailyCheckpointResponse): RecordEntry {
  const label = cp.checkpoint_type === 'morning' ? 'Morning check-in' : 'Night check-out';

  const parts: string[] = [];
  if (cp.mood != null) parts.push(`Mood ${cp.mood}`);
  if (cp.energy != null) parts.push(`Energy ${cp.energy}`);
  if (cp.sleep_quality != null) parts.push(`Sleep ${cp.sleep_quality}`);
  if (cp.body_state_score != null) parts.push(`Body ${cp.body_state_score}`);

  return {
    id: cp.id,
    type: 'checkpoint',
    timestamp: cp.checkpoint_at,
    label,
    summary: parts.length > 0 ? parts.join(' · ') : 'No scores recorded',
    detail: cp.notes,
  };
}

function buildSymptomEntry(sl: SymptomLogResponse): RecordEntry {
  const label =
    sl.symptom_name ??
    (sl.symptom_slug ? sl.symptom_slug.replace(/_/g, ' ') : 'Symptom');

  return {
    id: sl.id,
    type: 'symptom',
    timestamp: sl.started_at,
    label,
    summary: `intensity ${sl.intensity} · ${sl.status}`,
    detail: null,
  };
}

function buildTemperatureEntry(m: MeasurementResponse): RecordEntry {
  return {
    id: m.id,
    type: 'temperature',
    timestamp: m.measured_at,
    label: 'Temperature',
    summary: `${Number(m.value_num).toFixed(1)} ${m.unit}`,
    detail: null,
  };
}

function buildScaleEntry(sr: LatestScaleReading): RecordEntry | null {
  if (!sr.measured_at) return null;

  const weight = sr.metrics['weight'];
  const bodyFat = sr.metrics['body_fat_pct'];

  const parts: string[] = [];
  if (weight) parts.push(`${Number(weight.value).toFixed(1)} kg`);
  if (bodyFat) parts.push(`body fat ${Number(bodyFat.value).toFixed(1)}%`);

  return {
    id: sr.raw_payload_id ?? 'scale-latest',
    type: 'scale',
    timestamp: sr.measured_at,
    label: 'Scale',
    summary: parts.length > 0 ? parts.join(' · ') : 'Reading captured',
    detail: null,
  };
}

// ── Main derivation ───────────────────────────────────────────────────────

export function deriveRecordViewModel(
  sources: RecordRawSources,
  filter: RecordFilter,
): RecordViewModel {
  const { date, windowDays } = sources;
  const windowStart = localDateSubDays(date, windowDays - 1);

  // Tagged entries: day key is computed per-source to preserve the correct
  // local date semantics for each type.
  const tagged: Array<{ dayKey: string; entry: RecordEntry }> = [];

  // Checkpoints: `checkpoint_date` is the authoritative local date provided
  // by the backend — use it directly instead of parsing `checkpoint_at` (UTC),
  // which would give the wrong day for late-night check-outs in UTC-offset zones.
  for (const cp of sources.checkpoints) {
    if (cp.checkpoint_date >= windowStart && cp.checkpoint_date <= date) {
      tagged.push({ dayKey: cp.checkpoint_date, entry: buildCheckpointEntry(cp) });
    }
  }

  // Symptoms: fetched without a date range; client-side window filter.
  for (const sl of sources.symptoms) {
    const dayKey = localDateKey(sl.started_at);
    if (dayKey >= windowStart && dayKey <= date) {
      tagged.push({ dayKey, entry: buildSymptomEntry(sl) });
    }
  }

  // Temperature: fetched by limit only; client-side window filter.
  for (const m of sources.temperature) {
    const dayKey = localDateKey(m.measured_at);
    if (dayKey >= windowStart && dayKey <= date) {
      tagged.push({ dayKey, entry: buildTemperatureEntry(m) });
    }
  }

  // Scale: latest reading only — include when within the active window.
  let scaleReadingIsHistorical = false;
  if (sources.scaleReading?.measured_at) {
    const dayKey = localDateKey(sources.scaleReading.measured_at);
    if (dayKey >= windowStart && dayKey <= date) {
      const entry = buildScaleEntry(sources.scaleReading);
      if (entry) {
        tagged.push({ dayKey, entry });
        scaleReadingIsHistorical = dayKey !== date;
      }
    }
  }

  // Apply type filter before grouping so empty day groups are never created.
  const filtered =
    filter === 'all' ? tagged : tagged.filter(({ entry }) => entry.type === filter);

  // Group into days.
  const groupMap = new Map<string, RecordEntry[]>();
  for (const { dayKey, entry } of filtered) {
    const bucket = groupMap.get(dayKey);
    if (bucket) {
      bucket.push(entry);
    } else {
      groupMap.set(dayKey, [entry]);
    }
  }

  // Build and sort day groups.
  const dayGroups: RecordDayGroup[] = [];
  for (const [dayDate, entries] of groupMap) {
    entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    dayGroups.push({
      date: dayDate,
      label: formatDayLabel(dayDate),
      isToday: dayDate === date,
      entries,
      entryCount: entries.length,
    });
  }
  dayGroups.sort((a, b) => b.date.localeCompare(a.date));

  return {
    dayGroups,
    totalEntries: filtered.length,
    windowDays,
    activeFilter: filter,
    isEmpty: filtered.length === 0,
    scaleReadingIsHistorical,
  };
}
