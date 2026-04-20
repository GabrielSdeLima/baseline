/**
 * B6C — Record regression tests
 *
 * Covers gaps not addressed by record-ui.test.tsx:
 *  1. fetchLatestScaleReading rejects → page renders with remaining entries
 *  2. fetchSymptomLogs rejects → page renders, checkpoints still visible
 *  3. fetchCheckpoints rejects → page renders, other source types still show
 *  4. Record never calls fetchSystemStatus (no dependency on system status)
 *  5. Window boundary: entry at window start included, entry the day before excluded
 *  6. Filter switching multiple times does not corrupt day groups
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Record from '../pages/Record';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementList,
  MeasurementResponse,
  ScaleMetric,
  SymptomLogList,
  SymptomLogResponse,
} from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────
// DATE = '2026-04-18'  (mocked todayISO)
// With windowDays = 30: windowStart = localDateSubDays('2026-04-18', 29) = '2026-03-20'

const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

const TODAY_NOON = '2026-04-18T12:00:00.000Z';    // safe mid-day
const TODAY_06 = '2026-04-18T06:00:00.000Z';
const TODAY_10 = '2026-04-18T10:00:00.000Z';
const YESTERDAY_NOON = '2026-04-17T12:00:00.000Z';
const WINDOW_START_NOON = '2026-03-20T12:00:00.000Z'; // first day in 30d window
const BEFORE_WINDOW_NOON = '2026-03-19T12:00:00.000Z'; // excluded

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    todayISO: () => DATE,
    nowISO: () => NOW,
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    fetchSystemStatus: vi.fn(), // not used by Record — presence verifies no accidental call
  };
});

// ── Fixtures ──────────────────────────────────────────────────────────────

function makeCheckpoints(
  items: Array<{ id?: string; type?: 'morning' | 'night'; date?: string; at?: string }>,
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
  items: Array<{ id?: string; slug?: string; startedAt?: string }>,
): SymptomLogList {
  const slItems: SymptomLogResponse[] = items.map(
    ({ id = 'sl-1', slug = 'headache', startedAt = TODAY_NOON }) => ({
      id,
      user_id: 'test-user-id',
      symptom_slug: slug,
      symptom_name: slug,
      intensity: 4,
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

function makeScaleReading(measuredAt: string): LatestScaleReading {
  const metrics: Record<string, ScaleMetric> = {
    weight: { slug: 'weight', value: '78.5', unit: 'kg', is_derived: false },
  };
  return {
    status: 'weight_only',
    measured_at: measuredAt,
    raw_payload_id: 'scale-1',
    decoder_version: '1.0',
    has_impedance: false,
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

// ── Render helper ──────────────────────────────────────────────────────────

function renderRecord() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Record />
    </QueryClientProvider>,
  );
}

// ── Default seeds ─────────────────────────────────────────────────────────

beforeEach(() => {
  vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
  vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms);
  vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
  vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  // fetchSystemStatus: intentionally NOT seeded — Record must not call it
});

afterEach(() => vi.clearAllMocks());

// ── Tests ──────────────────────────────────────────────────────────────────

describe('Record regression', () => {
  // 1. fetchLatestScaleReading rejects — page renders with remaining entries
  it('page renders with checkpoint entries when fetchLatestScaleReading rejects', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_NOON }]),
    );
    vi.mocked(client.fetchLatestScaleReading).mockRejectedValue(new Error('network'));

    renderRecord();

    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());
    // Checkpoint entry still visible
    expect(screen.getAllByTestId('record-entry').some(
      (e) => e.getAttribute('data-type') === 'checkpoint',
    )).toBe(true);
    // No scale entry (scaleReading = null after rejection)
    expect(screen.getAllByTestId('record-entry').some(
      (e) => e.getAttribute('data-type') === 'scale',
    )).toBe(false);
  });

  // 2. fetchSymptomLogs rejects — page renders, checkpoint entries still visible
  it('page renders with checkpoint entries when fetchSymptomLogs rejects', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_NOON }]),
    );
    vi.mocked(client.fetchSymptomLogs).mockRejectedValue(new Error('network'));

    renderRecord();

    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());
    // Checkpoint entry present
    const entries = screen.getAllByTestId('record-entry');
    expect(entries.some((e) => e.getAttribute('data-type') === 'checkpoint')).toBe(true);
    // No symptom entries (symptoms = [] after rejection)
    expect(entries.some((e) => e.getAttribute('data-type') === 'symptom')).toBe(false);
  });

  // 3. fetchCheckpoints rejects — page renders, temperature entry still visible
  it('page renders with temperature entry when fetchCheckpoints rejects', async () => {
    vi.mocked(client.fetchCheckpoints).mockRejectedValue(new Error('network'));
    vi.mocked(client.fetchMeasurements).mockResolvedValue(
      makeTemperatures([{ id: 'tmp', measuredAt: TODAY_NOON }]),
    );

    renderRecord();

    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());
    const entries = screen.getAllByTestId('record-entry');
    expect(entries.some((e) => e.getAttribute('data-type') === 'temperature')).toBe(true);
    // No checkpoint entries
    expect(entries.some((e) => e.getAttribute('data-type') === 'checkpoint')).toBe(false);
  });

  // 4. Record never calls fetchSystemStatus
  it('Record does not call fetchSystemStatus', async () => {
    renderRecord();

    // Wait for page to fully load (empty state since default seeds are empty)
    await waitFor(() =>
      screen.getByTestId('record-page') || screen.getByTestId('record-empty'),
    );

    expect(vi.mocked(client.fetchSystemStatus)).not.toHaveBeenCalled();
  });

  // 5. Window boundary: entry at window start included; entry day before excluded
  it('entry at window start (March 20) included; entry on March 19 excluded', async () => {
    // Both symptoms returned by the mock; derivation filters by window
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([
        { id: 'in-window', slug: 'headache', startedAt: WINDOW_START_NOON },
        { id: 'out-window', slug: 'fatigue', startedAt: BEFORE_WINDOW_NOON },
      ]),
    );

    renderRecord();

    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());

    // Only 1 day group (March 20); entry on March 19 excluded
    await waitFor(() => {
      const groups = screen.getAllByTestId('record-day-group');
      expect(groups).toHaveLength(1);
      expect(groups[0].getAttribute('data-date')).toBe('2026-03-20');
    });
    expect(screen.getAllByTestId('record-entry')).toHaveLength(1);
  });

  // 6. Filter switching multiple times does not corrupt day groups
  it('switching filters multiple times returns correct entry sets', async () => {
    // All three types on April 18 at different times (for consistent ordering)
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      makeCheckpoints([{ id: 'cp', date: DATE, at: TODAY_06 }]),
    );
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([{ id: 'sl', startedAt: TODAY_10 }]),
    );
    vi.mocked(client.fetchMeasurements).mockResolvedValue(
      makeTemperatures([{ id: 'tmp', measuredAt: TODAY_NOON }]),
    );

    renderRecord();
    await waitFor(() => expect(screen.getByTestId('record-page')).toBeInTheDocument());

    // All — 3 entries across 1 day group
    await waitFor(() => expect(screen.getAllByTestId('record-entry')).toHaveLength(3));

    // Switch to Symptoms
    fireEvent.click(screen.getByTestId('record-chip-symptom'));
    await waitFor(() => {
      const entries = screen.getAllByTestId('record-entry');
      expect(entries).toHaveLength(1);
      expect(entries[0].getAttribute('data-type')).toBe('symptom');
    });

    // Switch to Temperature
    fireEvent.click(screen.getByTestId('record-chip-temperature'));
    await waitFor(() => {
      const entries = screen.getAllByTestId('record-entry');
      expect(entries).toHaveLength(1);
      expect(entries[0].getAttribute('data-type')).toBe('temperature');
    });

    // Back to All — all 3 entries back, correct day group preserved
    fireEvent.click(screen.getByTestId('record-chip-all'));
    await waitFor(() => {
      expect(screen.getAllByTestId('record-entry')).toHaveLength(3);
      expect(screen.getAllByTestId('record-day-group')).toHaveLength(1);
    });
  });
});
