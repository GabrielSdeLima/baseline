/**
 * B6B — Record UI tests
 *
 * Coverage:
 *  1. Nav shows "Record", not "History"
 *  2. Clicking the Record nav tab renders the Record page
 *  3. Filter chips for all 5 types are rendered
 *  4. Clicking Symptoms chip shows only symptom entries
 *  5. Clicking Temperature chip shows only temperature entries
 *  6. Filter can empty days — empty state shown when all entries filtered out
 *  7. Day groups rendered in most-recent-first order
 *  8. Entries within a day rendered most-recent-first (timestamp desc)
 *  9. Empty state renders without crash when no data
 * 10. Scale caveat appears when scaleReadingIsHistorical = true
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import Record from '../pages/Record';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementList,
  MeasurementResponse,
  MedicationLogList,
  MedicationRegimenList,
  ScaleMetric,
  SymptomLogList,
  SymptomLogResponse,
  SystemStatusResponse,
} from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────
const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

const TODAY_NOON = '2026-04-18T12:00:00.000Z';
const TODAY_MORNING = '2026-04-18T06:00:00.000Z';
const YESTERDAY_NOON = '2026-04-17T12:00:00.000Z';

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../lib/scaleProfile', () => ({
  loadScaleProfile: () => ({}),
  saveScaleProfile: vi.fn(),
}));

vi.mock('../lib/scaleDevice', () => ({
  loadScaleDevice: () => null,
  saveScaleDevice: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    todayISO: () => DATE,
    nowISO: () => NOW,
    // Record queries
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    // Today-only queries (needed for full App render in nav tests)
    fetchMedicationLogs: vi.fn(),
    fetchActiveRegimens: vi.fn(),
    fetchSystemStatus: vi.fn(),
  };
});

// ── Fixtures ──────────────────────────────────────────────────────────────

function makeCheckpoints(
  items: Array<{
    id?: string;
    type?: 'morning' | 'night';
    date?: string;
    at?: string;
  }>,
): DailyCheckpointList {
  const cpItems: DailyCheckpointResponse[] = items.map(
    ({ id = 'cp-1', type = 'morning', date = DATE, at = TODAY_NOON }) => ({
      id,
      user_id: 'test-user-id',
      checkpoint_type: type,
      checkpoint_date: date,
      checkpoint_at: at,
      mood: null,
      energy: null,
      sleep_quality: null,
      body_state_score: null,
      notes: null,
    }),
  );
  return { items: cpItems, total: cpItems.length, offset: 0, limit: 30 };
}

function makeSymptoms(
  items: Array<{
    id?: string;
    slug?: string;
    name?: string;
    startedAt?: string;
  }>,
): SymptomLogList {
  const slItems: SymptomLogResponse[] = items.map(
    ({ id = 'sl-1', slug = 'headache', name = 'Headache', startedAt = TODAY_NOON }) => ({
      id,
      user_id: 'test-user-id',
      symptom_slug: slug,
      symptom_name: name,
      intensity: 5,
      status: 'active',
      started_at: startedAt,
    }),
  );
  return { items: slItems, total: slItems.length, offset: 0, limit: 50 };
}

function makeTemperatures(
  items: Array<{ id?: string; value?: number; measuredAt?: string }>,
): MeasurementList {
  const mItems: MeasurementResponse[] = items.map(
    ({ id = 'm-1', value = 37.2, measuredAt = TODAY_NOON }) => ({
      id,
      user_id: 'test-user-id',
      metric_type_slug: 'temperature',
      metric_type_name: 'Temperature',
      source_slug: 'manual',
      value_num: value,
      unit: '°C',
      measured_at: measuredAt,
      aggregation_level: 'daily',
    }),
  );
  return { items: mItems, total: mItems.length, offset: 0, limit: 30 };
}

function makeScaleReading(measuredAt: string, weight = '78.5'): LatestScaleReading {
  const metrics: Record<string, ScaleMetric> = {
    weight: { slug: 'weight', value: weight, unit: 'kg', is_derived: false },
    body_fat_pct: { slug: 'body_fat_pct', value: '18.2', unit: '%', is_derived: false },
  };
  return {
    status: 'full_reading',
    measured_at: measuredAt,
    raw_payload_id: 'scale-payload-1',
    decoder_version: '1.0',
    has_impedance: true,
    metrics,
  };
}

const emptyCheckpoints: DailyCheckpointList = { items: [], total: 0, offset: 0, limit: 30 };
const emptySymptoms: SymptomLogList = { items: [], total: 0, offset: 0, limit: 50 };
const emptyMeasurements: MeasurementList = { items: [], total: 0, offset: 0, limit: 30 };
const neverMeasuredScale: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};
const emptyRegimens: MedicationRegimenList = { items: [], total: 0, offset: 0, limit: 1 };
const emptyMedLogs: MedicationLogList = { items: [], total: 0, offset: 0, limit: 50 };
const defaultSystemStatus: SystemStatusResponse = {
  user_id: 'test-user-id',
  sources: [],
  agents: [],
  as_of: NOW,
};

// ── Helpers ────────────────────────────────────────────────────────────────

function seedRecordDefaults() {
  vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
  vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms);
  vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
  vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
}

function seedTodayDefaults() {
  vi.mocked(client.fetchMedicationLogs).mockResolvedValue(emptyMedLogs);
  vi.mocked(client.fetchActiveRegimens).mockResolvedValue(emptyRegimens);
  vi.mocked(client.fetchSystemStatus).mockResolvedValue(defaultSystemStatus);
}

function renderRecord() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Record />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  seedRecordDefaults();
  seedTodayDefaults();
});

afterEach(() => vi.clearAllMocks());

// ── Tests ──────────────────────────────────────────────────────────────────

describe('Record UI', () => {
  // 1. Nav shows "Record", not "History"
  it('Nav renders "Record" tab and does not render "History" tab', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId('today-trust')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^record$/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^history$/i })).toBeNull();
  });

  // 2. Clicking the Record nav tab renders the Record page
  it('clicking the Record nav tab renders the Record page', async () => {
    render(<App />);
    await waitFor(() => screen.getByTestId('today-trust'));
    fireEvent.click(screen.getByRole('button', { name: /^record$/i }));
    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());
    expect(screen.queryByTestId('today-trust')).toBeNull();
  });

  // 3. Filter chips for all 5 types are present
  it('filter strip renders chips for all 5 entry types', async () => {
    renderRecord();
    await waitFor(() => screen.getByTestId('record-filter-strip'));
    for (const id of ['all', 'checkpoint', 'symptom', 'temperature', 'scale']) {
      expect(screen.getByTestId(`record-chip-${id}`)).toBeInTheDocument();
    }
  });

  // 4. Clicking Symptoms chip shows only symptom entries
  it('Symptoms chip filters to symptom entries only', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_NOON }]),
    );
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([{ id: 'sl', startedAt: TODAY_NOON }]),
    );

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    fireEvent.click(screen.getByTestId('record-chip-symptom'));

    await waitFor(() => {
      const entries = screen.getAllByTestId('record-entry');
      expect(entries.every((e) => e.getAttribute('data-type') === 'symptom')).toBe(true);
    });
  });

  // 5. Clicking Temperature chip shows only temperature entries
  it('Temperature chip filters to temperature entries only', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_NOON }]),
    );
    vi.mocked(client.fetchMeasurements).mockResolvedValue(
      makeTemperatures([{ id: 'm', measuredAt: TODAY_NOON }]),
    );

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    fireEvent.click(screen.getByTestId('record-chip-temperature'));

    await waitFor(() => {
      const entries = screen.getAllByTestId('record-entry');
      expect(entries.every((e) => e.getAttribute('data-type') === 'temperature')).toBe(true);
    });
  });

  // 6. Filter empties all days → empty state shown, no day groups
  it('empty state shown when filter removes all entries', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ date: DATE, at: TODAY_NOON }]),
    );
    // No symptoms, no temperature — filtering to 'temperature' leaves nothing

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    fireEvent.click(screen.getByTestId('record-chip-temperature'));

    await waitFor(() => expect(screen.getByTestId('record-empty')).toBeInTheDocument());
    expect(screen.queryByTestId('record-day-group')).toBeNull();
  });

  // 7. Day groups appear in most-recent-first order
  it('day groups ordered most-recent-first', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([
        { id: 'cp-a', date: DATE, at: TODAY_NOON },
        { id: 'cp-b', date: '2026-04-17', at: YESTERDAY_NOON },
      ]),
    );

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    await waitFor(() => {
      const groups = screen.getAllByTestId('record-day-group');
      expect(groups.length).toBe(2);
      expect(groups[0].getAttribute('data-date')).toBe('2026-04-18');
      expect(groups[1].getAttribute('data-date')).toBe('2026-04-17');
    });
  });

  // 8. Entries within a day ordered most-recent-first (timestamp desc)
  it('entries within a day ordered by timestamp desc', async () => {
    // April 18: morning check-in at 06:00, symptom at 14:00
    // desc: symptom (14:00) before morning (06:00)
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_MORNING, type: 'morning' }]),
    );
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([{ id: 'sl', startedAt: TODAY_NOON }]),
    );

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    await waitFor(() => {
      const group = screen.getByTestId('record-day-group');
      const entries = group.querySelectorAll('[data-testid="record-entry"]');
      expect(entries.length).toBe(2);
      // noon (12:00) > morning (06:00): symptom first
      expect(entries[0].getAttribute('data-type')).toBe('symptom');
      expect(entries[1].getAttribute('data-type')).toBe('checkpoint');
    });
  });

  // 9. Empty state renders without crash when no data at all
  it('empty state renders without crash when all sources are empty', async () => {
    // Default mocks return empty everywhere
    renderRecord();
    await waitFor(() => expect(screen.getByTestId('record-empty')).toBeInTheDocument());
    expect(screen.queryByTestId('record-day-group')).toBeNull();
  });

  // 10. Scale caveat appears when the reading is not from today
  it('scale caveat shown when scale reading is not from today', async () => {
    // Scale reading from yesterday → scaleReadingIsHistorical = true
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(
      makeScaleReading(YESTERDAY_NOON),
    );

    renderRecord();
    await waitFor(() => screen.getByTestId('record-page'));

    await waitFor(() =>
      expect(screen.getByTestId('record-scale-caveat')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('record-scale-caveat').textContent).toMatch(
      /latest available scale reading/i,
    );
  });
});
