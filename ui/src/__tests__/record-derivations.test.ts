/**
 * B6A — Record derivation tests
 *
 * Coverage:
 *   localDateKey / localDateSubDays helpers
 *   Day grouping (including local-date convention for checkpoints)
 *   Within-day ordering (timestamp desc)
 *   Window filter (30-day default; inclusive boundaries)
 *   Filter by entry type + empty-day pruning
 *   Checkpoint entry building (label, summary, scores, notes)
 *   Symptom entry building (name fallbacks, summary)
 *   Temperature entry building (label, summary, unit)
 *   Scale entry building (full_reading vs weight_only, scaleReadingIsHistorical)
 *   Empty states and totals
 */
import { describe, it, expect } from 'vitest';
import {
  deriveRecordViewModel,
  localDateKey,
  localDateSubDays,
} from '../features/record/deriveRecordViewModel';
import type { RecordRawSources } from '../features/record/types';
import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementResponse,
  ScaleMetric,
  SymptomLogResponse,
} from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────
// DATE = 2026-04-18  (sources.date / "today")
// With windowDays = 30: windowStart = localDateSubDays('2026-04-18', 29) = '2026-03-20'
//   (verified: April 18 − 29 days = March 20)

const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

// Safe mid-day timestamps — noon UTC is unambiguous across all timezones
const TODAY_NOON = '2026-04-18T12:00:00.000Z'; // localDateKey → '2026-04-18'
const YESTERDAY_NOON = '2026-04-17T12:00:00.000Z'; // → '2026-04-17'
const DAY_BEFORE_NOON = '2026-04-16T12:00:00.000Z'; // → '2026-04-16'
const TODAY_MORNING = '2026-04-18T06:00:00.000Z'; // → '2026-04-18'
const TODAY_EVENING = '2026-04-18T22:00:00.000Z'; // → '2026-04-18'
const WINDOW_START_NOON = '2026-03-20T12:00:00.000Z'; // March 20 — first day in 30d window
const BEFORE_WINDOW_NOON = '2026-03-19T12:00:00.000Z'; // March 19 — excluded

// ── Fixture builders ──────────────────────────────────────────────────────

function makeCheckpoint(overrides: Partial<{
  id: string;
  type: 'morning' | 'night';
  date: string;
  at: string;
  mood: number | null;
  energy: number | null;
  sleep: number | null;
  body: number | null;
  notes: string | null;
}> = {}): DailyCheckpointResponse {
  const {
    id = 'cp-1', type = 'morning', date = DATE, at = TODAY_NOON,
    mood = null, energy = null, sleep = null, body = null, notes = null,
  } = overrides;
  return {
    id,
    user_id: 'u1',
    checkpoint_type: type,
    checkpoint_date: date,
    checkpoint_at: at,
    mood,
    energy,
    sleep_quality: sleep,
    body_state_score: body,
    notes,
  };
}

function makeSymptom(overrides: Partial<{
  id: string;
  slug: string | null;
  name: string | null;
  intensity: number;
  status: string;
  startedAt: string;
}> = {}): SymptomLogResponse {
  const {
    id = 'sl-1', slug = 'headache', name = 'Headache',
    intensity = 5, status = 'active', startedAt = TODAY_NOON,
  } = overrides;
  return {
    id,
    user_id: 'u1',
    symptom_slug: slug,
    symptom_name: name,
    intensity,
    status,
    started_at: startedAt,
  };
}

function makeTemperature(overrides: Partial<{
  id: string;
  value: number;
  unit: string;
  measuredAt: string;
}> = {}): MeasurementResponse {
  const { id = 'm-1', value = 37.2, unit = '°C', measuredAt = TODAY_NOON } = overrides;
  return {
    id,
    user_id: 'u1',
    metric_type_slug: 'temperature',
    metric_type_name: 'Temperature',
    source_slug: 'manual',
    value_num: value,
    unit,
    measured_at: measuredAt,
    aggregation_level: 'daily',
  };
}

function makeScale(overrides: Partial<{
  measuredAt: string;
  weight: string;
  bodyFatPct: string | null;
  rawPayloadId: string;
}> = {}): LatestScaleReading {
  const {
    measuredAt = TODAY_NOON,
    weight = '78.5',
    bodyFatPct = '18.2',
    rawPayloadId = 'scale-id-1',
  } = overrides;

  const metrics: Record<string, ScaleMetric> = {
    weight: { slug: 'weight', value: weight, unit: 'kg', is_derived: false },
  };
  if (bodyFatPct !== null) {
    metrics['body_fat_pct'] = {
      slug: 'body_fat_pct', value: bodyFatPct, unit: '%', is_derived: false,
    };
  }

  return {
    status: bodyFatPct !== null ? 'full_reading' : 'weight_only',
    measured_at: measuredAt,
    raw_payload_id: rawPayloadId,
    decoder_version: '1.0',
    has_impedance: bodyFatPct !== null,
    metrics,
  };
}

function emptySources(overrides: Partial<RecordRawSources> = {}): RecordRawSources {
  return {
    date: DATE,
    now: NOW,
    windowDays: 30,
    checkpoints: [],
    symptoms: [],
    temperature: [],
    scaleReading: null,
    ...overrides,
  };
}

// ── localDateKey helper ───────────────────────────────────────────────────

describe('localDateKey', () => {
  it('returns YYYY-MM-DD for a noon UTC timestamp (safe, zone-independent)', () => {
    // Noon UTC is mid-day regardless of timezone offset
    expect(localDateKey('2026-04-18T12:00:00.000Z')).toBe('2026-04-18');
  });

  it('reflects local date via JS Date methods, not UTC .slice(0,10)', () => {
    // The function uses d.getFullYear/Month/Date (local), not toISOString().slice(0,10) (UTC).
    // For any timestamp ts, localDateKey(ts) must equal what new Date(ts) reports locally.
    const ts = '2026-04-17T23:30:00.000Z';
    const d = new Date(ts);
    const expected =
      d.getFullYear() +
      '-' +
      String(d.getMonth() + 1).padStart(2, '0') +
      '-' +
      String(d.getDate()).padStart(2, '0');
    expect(localDateKey(ts)).toBe(expected);
  });
});

// ── localDateSubDays helper ───────────────────────────────────────────────

describe('localDateSubDays', () => {
  it('subtracts n calendar days from a date string', () => {
    // 29 days before 2026-04-18 = 2026-03-20 (verified manually)
    expect(localDateSubDays('2026-04-18', 29)).toBe('2026-03-20');
  });

  it('returns a YYYY-MM-DD string', () => {
    const result = localDateSubDays('2026-04-18', 0);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

// ── Day grouping ──────────────────────────────────────────────────────────

describe('day grouping', () => {
  it('entries on the same day grouped into one RecordDayGroup', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'cp-1', type: 'morning', at: TODAY_MORNING }),
        makeCheckpoint({ id: 'cp-2', type: 'night', at: TODAY_EVENING }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].entries).toHaveLength(2);
  });

  it('entries on different days create separate groups', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'cp-1', date: DATE, at: TODAY_NOON }),
        makeCheckpoint({ id: 'cp-2', date: '2026-04-17', at: YESTERDAY_NOON }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(2);
  });

  it('day groups sorted most recent first', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'cp-old', date: '2026-04-16', at: DAY_BEFORE_NOON }),
        makeCheckpoint({ id: 'cp-new', date: DATE, at: TODAY_NOON }),
        makeCheckpoint({ id: 'cp-mid', date: '2026-04-17', at: YESTERDAY_NOON }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].date).toBe('2026-04-18');
    expect(vm.dayGroups[1].date).toBe('2026-04-17');
    expect(vm.dayGroups[2].date).toBe('2026-04-16');
  });

  it('isToday is true only for the group matching sources.date', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'today', date: DATE, at: TODAY_NOON }),
        makeCheckpoint({ id: 'yday', date: '2026-04-17', at: YESTERDAY_NOON }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    const todayGroup = vm.dayGroups.find((g) => g.date === DATE);
    const yestGroup = vm.dayGroups.find((g) => g.date === '2026-04-17');
    expect(todayGroup?.isToday).toBe(true);
    expect(yestGroup?.isToday).toBe(false);
  });

  it('day label formatted as "Apr 18 Fri"', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ date: DATE, at: TODAY_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].label).toBe('Apr 18 Sat');
  });

  it('entryCount matches number of entries in the group', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'a', type: 'morning', at: TODAY_MORNING }),
        makeCheckpoint({ id: 'b', type: 'night', at: TODAY_EVENING }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entryCount).toBe(2);
  });

  it('days with no visible entries after filtering are omitted', () => {
    // April 17 has only a symptom; filter=checkpoint → April 17 group disappears
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ date: DATE, at: TODAY_NOON })],
      symptoms: [makeSymptom({ startedAt: YESTERDAY_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'checkpoint');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].date).toBe(DATE);
  });

  // Local date convention: checkpoint grouped by checkpoint_date, not checkpoint_at UTC day
  it('checkpoint uses checkpoint_date for grouping, not checkpoint_at UTC slice', () => {
    // Simulates night check-out at 23:00 local in UTC-3 → checkpoint_at = next-day UTC.
    // The entry must appear under checkpoint_date (2026-04-17), not the UTC day (2026-04-18).
    const cp = makeCheckpoint({
      id: 'night-late',
      type: 'night',
      date: '2026-04-17',               // local date (backend-provided)
      at: '2026-04-18T02:00:00.000Z',   // UTC next day
    });
    const sources = emptySources({ checkpoints: [cp] });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].date).toBe('2026-04-17');
  });
});

// ── Within-day ordering ───────────────────────────────────────────────────

describe('within-day ordering', () => {
  it('entries sorted by timestamp desc within a day group', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'morning', type: 'morning', at: TODAY_MORNING }),
        makeCheckpoint({ id: 'night', type: 'night', at: TODAY_EVENING }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    const entries = vm.dayGroups[0].entries;
    // Evening (22:00) comes before morning (06:00) in desc order
    expect(entries[0].id).toBe('night');
    expect(entries[1].id).toBe('morning');
  });

  it('mixed types on same day sorted by timestamp desc', () => {
    // symptom at 08:00, temperature at 14:00 → temperature first in desc order
    const sources = emptySources({
      symptoms: [makeSymptom({ id: 'sl', startedAt: TODAY_MORNING })],
      temperature: [makeTemperature({ id: 'tmp', measuredAt: TODAY_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    const entries = vm.dayGroups[0].entries;
    expect(entries[0].id).toBe('tmp');  // noon > morning
    expect(entries[1].id).toBe('sl');
  });
});

// ── Window filter ─────────────────────────────────────────────────────────

describe('window filter (30 days)', () => {
  it('entry on the first day of the window (March 20) is included', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ startedAt: WINDOW_START_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].date).toBe('2026-03-20');
  });

  it('entry one day before the window start (March 19) is excluded', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ startedAt: BEFORE_WINDOW_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(0);
    expect(vm.isEmpty).toBe(true);
  });

  it('entry on today (April 18) is included', () => {
    const sources = emptySources({
      temperature: [makeTemperature({ measuredAt: TODAY_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].date).toBe(DATE);
  });

  it('symptom from outside the window is excluded', () => {
    const sources = emptySources({
      symptoms: [
        makeSymptom({ id: 'in', startedAt: TODAY_NOON }),
        makeSymptom({ id: 'out', startedAt: BEFORE_WINDOW_NOON }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.totalEntries).toBe(1);
    expect(vm.dayGroups[0].entries[0].id).toBe('in');
  });

  it('checkpoint with checkpoint_date before window start is excluded', () => {
    const cp = makeCheckpoint({ date: '2026-03-19', at: BEFORE_WINDOW_NOON });
    const sources = emptySources({ checkpoints: [cp] });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.isEmpty).toBe(true);
  });
});

// ── Filter by type ────────────────────────────────────────────────────────

describe('filter by type', () => {
  function sourceWithAllTypes(): RecordRawSources {
    return emptySources({
      checkpoints: [makeCheckpoint()],
      symptoms: [makeSymptom()],
      temperature: [makeTemperature()],
      scaleReading: makeScale(),
    });
  }

  it('filter=all shows all entry types', () => {
    const vm = deriveRecordViewModel(sourceWithAllTypes(), 'all');
    const types = vm.dayGroups.flatMap((g) => g.entries.map((e) => e.type));
    expect(types).toContain('checkpoint');
    expect(types).toContain('symptom');
    expect(types).toContain('temperature');
    expect(types).toContain('scale');
    expect(vm.totalEntries).toBe(4);
  });

  it('filter=checkpoint shows only checkpoints', () => {
    const vm = deriveRecordViewModel(sourceWithAllTypes(), 'checkpoint');
    const types = new Set(vm.dayGroups.flatMap((g) => g.entries.map((e) => e.type)));
    expect(types).toEqual(new Set(['checkpoint']));
  });

  it('filter=symptom shows only symptoms', () => {
    const vm = deriveRecordViewModel(sourceWithAllTypes(), 'symptom');
    const types = new Set(vm.dayGroups.flatMap((g) => g.entries.map((e) => e.type)));
    expect(types).toEqual(new Set(['symptom']));
  });

  it('filter=temperature shows only temperature entries', () => {
    const vm = deriveRecordViewModel(sourceWithAllTypes(), 'temperature');
    const types = new Set(vm.dayGroups.flatMap((g) => g.entries.map((e) => e.type)));
    expect(types).toEqual(new Set(['temperature']));
  });

  it('filter=scale shows only scale entries', () => {
    const vm = deriveRecordViewModel(sourceWithAllTypes(), 'scale');
    const types = new Set(vm.dayGroups.flatMap((g) => g.entries.map((e) => e.type)));
    expect(types).toEqual(new Set(['scale']));
  });

  it('activeFilter reflects the filter argument', () => {
    expect(deriveRecordViewModel(sourceWithAllTypes(), 'symptom').activeFilter).toBe('symptom');
    expect(deriveRecordViewModel(sourceWithAllTypes(), 'all').activeFilter).toBe('all');
  });

  it('filter that removes all entries of a day drops that day group', () => {
    // April 18: checkpoint + symptom; April 17: symptom only
    // filter=checkpoint → April 17 group disappears
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ date: DATE, at: TODAY_NOON })],
      symptoms: [
        makeSymptom({ id: 'sl-today', startedAt: TODAY_MORNING }),
        makeSymptom({ id: 'sl-yday', startedAt: YESTERDAY_NOON }),
      ],
    });
    const vm = deriveRecordViewModel(sources, 'checkpoint');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].date).toBe(DATE);
  });

  it('filter that eliminates all entries → isEmpty = true', () => {
    const sources = emptySources({ symptoms: [makeSymptom()] });
    const vm = deriveRecordViewModel(sources, 'temperature'); // no temperature entries
    expect(vm.isEmpty).toBe(true);
    expect(vm.totalEntries).toBe(0);
    expect(vm.dayGroups).toHaveLength(0);
  });
});

// ── Checkpoint entries ────────────────────────────────────────────────────

describe('checkpoint entries', () => {
  it('morning type → label "Morning check-in"', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ type: 'morning' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Morning check-in');
  });

  it('night type → label "Night check-out"', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ type: 'night' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Night check-out');
  });

  it('summary includes all non-null scores joined by ·', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ mood: 7, energy: 6, sleep: 5, body: 8 })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('Mood 7 · Energy 6 · Sleep 5 · Body 8');
  });

  it('summary omits null scores', () => {
    // Only mood and energy set; sleep and body are null
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ mood: 7, energy: 6 })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('Mood 7 · Energy 6');
    expect(vm.dayGroups[0].entries[0].summary).not.toContain('Sleep');
  });

  it('summary = "No scores recorded" when all scores are null', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint()], // all scores null by default
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('No scores recorded');
  });

  it('detail = notes field when present', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ notes: 'feeling off today' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].detail).toBe('feeling off today');
  });

  it('detail = null when notes is null', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint({ notes: null })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].detail).toBeNull();
  });
});

// ── Symptom entries ───────────────────────────────────────────────────────

describe('symptom entries', () => {
  it('label = symptom_name when present', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ name: 'Tension headache' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Tension headache');
  });

  it('label falls back to slug with underscores → spaces when name is null', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ name: null, slug: 'lower_back_pain' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('lower back pain');
  });

  it('label = "Symptom" when both name and slug are null', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ name: null, slug: null })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Symptom');
  });

  it('summary = "intensity X · status"', () => {
    const sources = emptySources({
      symptoms: [makeSymptom({ intensity: 4, status: 'resolving' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('intensity 4 · resolving');
  });

  it('symptom grouped by localDateKey(started_at)', () => {
    // Use a safe timestamp; verify the day key matches localDateKey
    const ts = YESTERDAY_NOON;
    const sources = emptySources({ symptoms: [makeSymptom({ startedAt: ts })] });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].date).toBe(localDateKey(ts)); // '2026-04-17'
  });
});

// ── Temperature entries ───────────────────────────────────────────────────

describe('temperature entries', () => {
  it('label = "Temperature"', () => {
    const sources = emptySources({ temperature: [makeTemperature()] });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Temperature');
  });

  it('summary = "XX.X unit"', () => {
    const sources = emptySources({
      temperature: [makeTemperature({ value: 37.6, unit: '°C' })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('37.6 °C');
  });

  it('temperature outside the window is excluded', () => {
    const sources = emptySources({
      temperature: [makeTemperature({ measuredAt: BEFORE_WINDOW_NOON })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.isEmpty).toBe(true);
  });
});

// ── Scale entries ─────────────────────────────────────────────────────────

describe('scale entries', () => {
  it('scale within the window creates an entry in the correct day group', () => {
    const sources = emptySources({ scaleReading: makeScale({ measuredAt: YESTERDAY_NOON }) });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups).toHaveLength(1);
    expect(vm.dayGroups[0].date).toBe('2026-04-17');
    expect(vm.dayGroups[0].entries[0].type).toBe('scale');
  });

  it('scale entry label = "Scale"', () => {
    const sources = emptySources({ scaleReading: makeScale() });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].label).toBe('Scale');
  });

  it('full_reading summary shows weight and body fat', () => {
    const sources = emptySources({
      scaleReading: makeScale({ weight: '78.5', bodyFatPct: '18.2' }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('78.5 kg · body fat 18.2%');
  });

  it('weight_only summary shows weight only (no body fat)', () => {
    const sources = emptySources({
      scaleReading: makeScale({ weight: '79.0', bodyFatPct: null }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.dayGroups[0].entries[0].summary).toBe('79.0 kg');
    expect(vm.dayGroups[0].entries[0].summary).not.toContain('body fat');
  });

  it('scale outside the window is excluded', () => {
    const sources = emptySources({
      scaleReading: makeScale({ measuredAt: BEFORE_WINDOW_NOON }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.isEmpty).toBe(true);
  });

  it('scale with measured_at = null is excluded', () => {
    const scaleReading: LatestScaleReading = {
      status: 'never_measured',
      measured_at: null,
      raw_payload_id: null,
      decoder_version: null,
      has_impedance: false,
      metrics: {},
    };
    const sources = emptySources({ scaleReading });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.isEmpty).toBe(true);
  });

  it('scaleReadingIsHistorical = false when scale is from today', () => {
    const sources = emptySources({
      scaleReading: makeScale({ measuredAt: TODAY_NOON }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.scaleReadingIsHistorical).toBe(false);
  });

  it('scaleReadingIsHistorical = true when scale is within window but not today', () => {
    const sources = emptySources({
      scaleReading: makeScale({ measuredAt: YESTERDAY_NOON }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.scaleReadingIsHistorical).toBe(true);
  });

  it('scaleReadingIsHistorical = false when scale is outside window (entry absent)', () => {
    const sources = emptySources({
      scaleReading: makeScale({ measuredAt: BEFORE_WINDOW_NOON }),
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.scaleReadingIsHistorical).toBe(false); // no entry was added
  });
});

// ── Empty state ───────────────────────────────────────────────────────────

describe('empty state', () => {
  it('isEmpty = true with no sources', () => {
    const vm = deriveRecordViewModel(emptySources(), 'all');
    expect(vm.isEmpty).toBe(true);
    expect(vm.dayGroups).toHaveLength(0);
    expect(vm.totalEntries).toBe(0);
  });

  it('isEmpty = true when filter removes all entries', () => {
    const sources = emptySources({ symptoms: [makeSymptom()] });
    const vm = deriveRecordViewModel(sources, 'temperature');
    expect(vm.isEmpty).toBe(true);
  });

  it('isEmpty = false when at least one entry is visible', () => {
    const sources = emptySources({ symptoms: [makeSymptom()] });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.isEmpty).toBe(false);
  });
});

// ── Totals and metadata ───────────────────────────────────────────────────

describe('totals and metadata', () => {
  it('totalEntries counts all visible entries across all day groups', () => {
    const sources = emptySources({
      checkpoints: [
        makeCheckpoint({ id: 'a', date: DATE, at: TODAY_NOON }),
        makeCheckpoint({ id: 'b', date: '2026-04-17', at: YESTERDAY_NOON }),
      ],
      symptoms: [makeSymptom({ id: 'c', startedAt: TODAY_MORNING })],
    });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.totalEntries).toBe(3);
  });

  it('totalEntries respects active filter', () => {
    const sources = emptySources({
      checkpoints: [makeCheckpoint()],
      symptoms: [makeSymptom()],
    });
    expect(deriveRecordViewModel(sources, 'checkpoint').totalEntries).toBe(1);
    expect(deriveRecordViewModel(sources, 'symptom').totalEntries).toBe(1);
    expect(deriveRecordViewModel(sources, 'all').totalEntries).toBe(2);
  });

  it('windowDays reflected in the ViewModel', () => {
    const sources = emptySources({ windowDays: 14 });
    const vm = deriveRecordViewModel(sources, 'all');
    expect(vm.windowDays).toBe(14);
  });
});
