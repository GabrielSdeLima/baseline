/**
 * Progress UI tests — verify that the Progress page renders the ProgressViewModel
 * correctly.  Analytical logic is already covered by progress-derivations.test.ts;
 * these tests check only that the UI reflects the VM output faithfully.
 *
 * Coverage:
 *  1. header / hero with overallState = 'sufficient'
 *  2. header / hero with overallState = 'limited' / 'no_data'
 *  3. ConsistencyCard with sufficient data
 *  4. ConsistencyCard with caveat (limited confidence)
 *  5. SignalDirectionCard with HRV up + RHR stable
 *  6. SignalDirectionCard with insufficient data
 *  7. ReportedSymptomBurdenCard with direction = 'unclear'
 *  8. ReportedSymptomBurdenCard shows topSymptom
 *  9. DataConfidenceCard shows both freshness + analytical dimensions
 * 10. Page renders without crash when overallState = 'no_data'
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Progress from '../pages/Progress';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  DailyCheckpointResponse,
  InsightSummary,
  MeasurementList,
  MeasurementResponse,
  MedicationAdherenceResponse,
  SymptomLogList,
  SymptomLogResponse,
  SystemStatusResponse,
} from '../api/types';

// ── Time anchors ──────────────────────────────────────────────────────────
//   NOW   = 2026-04-18 14:00 UTC
//   Recent window (>NOW-7d, ≤NOW): safe timestamps at noon 2026-04-12 to 2026-04-18
//   Prior window (>NOW-14d, ≤NOW-7d): safe timestamps at noon 2026-04-05 to 2026-04-11

const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

const RECENT = [
  '2026-04-12T12:00:00.000Z',
  '2026-04-13T12:00:00.000Z',
  '2026-04-14T12:00:00.000Z',
  '2026-04-15T12:00:00.000Z',
];
const PRIOR = [
  '2026-04-05T12:00:00.000Z',
  '2026-04-06T12:00:00.000Z',
  '2026-04-07T12:00:00.000Z',
  '2026-04-08T12:00:00.000Z',
];

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
    fetchMedicationAdherence: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchSummary: vi.fn(),
    fetchSystemStatus: vi.fn(),
  };
});

// ── Fixture builders ──────────────────────────────────────────────────────

function emptyCheckpoints(): DailyCheckpointList {
  return { items: [], total: 0, offset: 0, limit: 14 };
}

function makeCheckpoints(n: number): DailyCheckpointList {
  const items: DailyCheckpointResponse[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(`${DATE}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - i);
    const date = d.toISOString().slice(0, 10);
    items.push({
      id: `cp-${i}`,
      user_id: 'test-user-id',
      checkpoint_type: 'morning',
      checkpoint_date: date,
      checkpoint_at: `${date}T08:00:00.000Z`,
      mood: null,
      energy: null,
      sleep_quality: null,
      body_state_score: null,
      notes: null,
    });
  }
  return { items, total: n, offset: 0, limit: 14 };
}

function emptyMeasurements(): MeasurementList {
  return { items: [], total: 0, offset: 0, limit: 14 };
}

function makeMeasurements(
  slug: string,
  unit: string,
  readings: Array<[number, string]>,
): MeasurementList {
  const items: MeasurementResponse[] = readings.map(([value, measuredAt], i) => ({
    id: `m-${i}`,
    user_id: 'test-user-id',
    metric_type_slug: slug,
    metric_type_name: slug,
    source_slug: 'garmin_connect',
    value_num: value,
    unit,
    measured_at: measuredAt,
    aggregation_level: 'daily',
  }));
  return { items, total: items.length, offset: 0, limit: 14 };
}

function emptySymptoms(): SymptomLogList {
  return { items: [], total: 0, offset: 0, limit: 50 };
}

function makeSymptoms(logs: Array<[string, string]>): SymptomLogList {
  const items: SymptomLogResponse[] = logs.map(([slug, startedAt], i) => ({
    id: `sym-${i}`,
    user_id: 'test-user-id',
    symptom_slug: slug,
    symptom_name: slug,
    intensity: 5,
    status: 'active',
    started_at: startedAt,
  }));
  return { items, total: items.length, offset: 0, limit: 50 };
}

const emptyAdherence: MedicationAdherenceResponse = {
  user_id: 'test-user-id',
  items: [],
  overall_adherence_pct: null,
  availability_status: 'not_applicable',
};

function makeSystemStatus(
  garminConfigured = true,
  scalePaired = true,
): SystemStatusResponse {
  return {
    user_id: 'test-user-id',
    sources: [
      {
        source_slug: 'garmin_connect',
        integration_configured: garminConfigured,
        device_paired: null,
        last_sync_at: NOW,
        last_advanced_at: NOW,
        last_run_status: 'ok',
        last_run_at: NOW,
      },
      {
        source_slug: 'hc900_ble',
        integration_configured: true,
        device_paired: scalePaired,
        last_sync_at: NOW,
        last_advanced_at: NOW,
        last_run_status: 'ok',
        last_run_at: NOW,
      },
    ],
    agents: [],
    as_of: NOW,
  };
}

function makeSummary(
  blocksOk: number = 5,
): InsightSummary {
  const allOk = { deviations: 'ok', illness: 'ok', recovery: 'ok', adherence: 'ok', symptoms: 'ok' } as const;
  const somePartial = { ...allOk, recovery: 'no_data', adherence: 'no_data' } as const;
  return {
    user_id: 'test-user-id',
    as_of: NOW,
    overall_adherence_pct: null,
    active_deviations: 0,
    current_symptom_burden: 0,
    illness_signal: 'none',
    recovery_status: 'normal',
    block_availability: blocksOk === 5 ? allOk : somePartial,
    data_availability: null,
  };
}

// ── Render helper ─────────────────────────────────────────────────────────

function renderProgress() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Progress />
    </QueryClientProvider>,
  );
}

// ── Default mocks (overridden per test) ───────────────────────────────────

beforeEach(() => {
  vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints());
  vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms());
  vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(emptyAdherence);
  vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements());
  vi.mocked(client.fetchSummary).mockResolvedValue(makeSummary(5));
  vi.mocked(client.fetchSystemStatus).mockResolvedValue(makeSystemStatus());
});

afterEach(() => vi.clearAllMocks());

// ── Tests ─────────────────────────────────────────────────────────────────

describe('Progress UI', () => {
  // 1. Hero with overallState = 'sufficient'
  it('renders "Sufficient data" chip when overallState = sufficient', async () => {
    // 10 checkpoints → rate 71% → sufficient consistency
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(10));
    // HRV + RHR with 3 readings each in both windows → sufficient signal
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'hrv_rmssd')
        return Promise.resolve(
          makeMeasurements('hrv_rmssd', 'ms', [
            [56, RECENT[0]], [56, RECENT[1]], [56, RECENT[2]],
            [48, PRIOR[0]], [48, PRIOR[1]], [48, PRIOR[2]],
          ]),
        );
      if (slug === 'resting_hr')
        return Promise.resolve(
          makeMeasurements('resting_hr', 'bpm', [
            [60, RECENT[0]], [60, RECENT[1]], [60, RECENT[2]],
            [60, PRIOR[0]], [60, PRIOR[1]], [60, PRIOR[2]],
          ]),
        );
      return Promise.resolve(emptyMeasurements());
    });

    renderProgress();

    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());
    const chip = screen.getByTestId('progress-overall-state');
    expect(chip.getAttribute('data-state')).toBe('sufficient');
    expect(chip.textContent).toMatch(/sufficient data/i);
  });

  // 2. Hero with overallState = 'limited'
  it('renders "Collecting data" chip and collecting headline when overallState = limited', async () => {
    // Default: 0 checkpoints + no measurements → both blocks insufficient → limited
    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());
    const chip = screen.getByTestId('progress-overall-state');
    expect(chip.getAttribute('data-state')).toBe('limited');
    expect(chip.textContent).toMatch(/collecting data/i);
    // Headline should say "collecting" or "few more days"
    const hero = screen.getByTestId('progress-hero');
    expect(hero.textContent).toMatch(/collecting data/i);
  });

  // 3. ConsistencyCard with sufficient data shows rate
  it('ConsistencyCard shows check-in rate when data is sufficient', async () => {
    // 10 checkpoints → 10/14 ≈ 71%
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(10));

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-consistency')).toBeInTheDocument());

    const card = screen.getByTestId('progress-consistency');
    // Should show "10/14 days" and "71%"
    expect(card.textContent).toContain('10/14 days');
    expect(card.textContent).toContain('71%');
    // No caveat when sufficient
    expect(card.textContent).not.toMatch(/too sparse/i);
    expect(card.textContent).not.toMatch(/trend forming/i);
  });

  // 4. ConsistencyCard with caveat (limited confidence)
  it('ConsistencyCard shows caveat when data confidence is limited', async () => {
    // 8 checkpoints → 8/14 ≈ 57% → limited (≥0.5 but <0.7)
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(8));

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-consistency')).toBeInTheDocument());

    const card = screen.getByTestId('progress-consistency');
    expect(card.textContent).toMatch(/trend forming/i);
  });

  // 5. SignalDirectionCard with HRV up + RHR stable
  it('SignalDirectionCard shows "↑ up" for HRV and "→ stable" for RHR', async () => {
    // HRV: recent=56, prior=48 → +16.7% > 8% → up
    // RHR: recent=60, prior=61 → +1 bpm < 3 bpm → stable
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'hrv_rmssd')
        return Promise.resolve(
          makeMeasurements('hrv_rmssd', 'ms', [
            [56, RECENT[0]], [56, RECENT[1]], [56, RECENT[2]],
            [48, PRIOR[0]], [48, PRIOR[1]], [48, PRIOR[2]],
          ]),
        );
      if (slug === 'resting_hr')
        return Promise.resolve(
          makeMeasurements('resting_hr', 'bpm', [
            [60, RECENT[0]], [60, RECENT[1]], [60, RECENT[2]],
            [61, PRIOR[0]], [61, PRIOR[1]], [61, PRIOR[2]],
          ]),
        );
      return Promise.resolve(emptyMeasurements());
    });

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-signal')).toBeInTheDocument());

    const hrvRow = screen.getByTestId('progress-signal-hrv');
    expect(hrvRow.textContent).toContain('↑ up');
    expect(hrvRow.textContent).toContain('56.0 ms');

    const rhrRow = screen.getByTestId('progress-signal-rhr');
    expect(rhrRow.textContent).toContain('→ stable');
    expect(rhrRow.textContent).toContain('60.0 bpm');
  });

  // 6. SignalDirectionCard with insufficient data
  it('SignalDirectionCard shows caveat when insufficient readings', async () => {
    // 7 checkpoints → consistency rate 7/14 = 50% → limited (score=1)
    // No measurements → signal insufficient (score=0) → total=1 → mixed
    // mixed state renders all blocks including SignalDirectionCard
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(7));

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-signal')).toBeInTheDocument());

    const card = screen.getByTestId('progress-signal');
    expect(card.textContent).toMatch(/3\+/);
    expect(card.textContent).not.toContain('↑ up');
    expect(card.textContent).not.toContain('↓ down');
  });

  // 7. ReportedSymptomBurdenCard with direction = 'unclear'
  it('symptom card shows "unclear" and caveat when logging inconsistent', async () => {
    // Low check-in rate: 5/14 ≈ 35% → inconsistent
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(5));
    // Recent logs = 1 < MIN_SYMPTOM_LOGS_FOR_DIRECTION → loggingConsistencyLow = true
    // Prior logs = 4 → would look like "improving" without the guard
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([
        ['headache', RECENT[0]],
        ['headache', PRIOR[0]],
        ['fatigue', PRIOR[1]],
        ['nausea', PRIOR[2]],
        ['headache', PRIOR[3]],
      ]),
    );

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-symptom')).toBeInTheDocument());

    const dirEl = screen.getByTestId('progress-symptom-direction');
    expect(dirEl.textContent).toContain('unclear');

    const card = screen.getByTestId('progress-symptom');
    expect(card.textContent).toMatch(/logging/i); // caveat mentions logging
    expect(card.textContent).not.toMatch(/improving/i); // NOT falsely "improving"
  });

  // 8. ReportedSymptomBurdenCard shows topSymptom
  it('symptom card shows most frequent recent symptom', async () => {
    // Consistent logging: 10 checkpoints
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(10));
    // Recent: headache ×2, fatigue ×1
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(
      makeSymptoms([
        ['headache', RECENT[0]],
        ['headache', RECENT[1]],
        ['fatigue', RECENT[2]],
        ['nausea', PRIOR[0]],
      ]),
    );

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-symptom')).toBeInTheDocument());

    const topEl = screen.getByTestId('progress-symptom-top');
    expect(topEl.textContent).toBe('headache');
  });

  // 9. DataConfidenceCard shows freshness + analytical coverage as separate sections
  it('DataConfidenceCard shows both freshness and analytical coverage', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(
      makeSystemStatus(true, false), // garmin ok, scale NOT paired
    );
    vi.mocked(client.fetchSummary).mockResolvedValue(makeSummary(3)); // 3/5 blocks ok

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-confidence')).toBeInTheDocument());

    const freshness = screen.getByTestId('progress-confidence-freshness');
    expect(freshness.textContent).toMatch(/garmin/i);
    expect(freshness.textContent).toContain('configured'); // garmin ok
    expect(freshness.textContent).toMatch(/scale/i);
    expect(freshness.textContent).toContain('not paired'); // scale not ok

    const analytical = screen.getByTestId('progress-confidence-analytical');
    expect(analytical.textContent).toMatch(/3\/5/); // 3 of 5 blocks have data (makeSummary(3) → somePartial = 3 ok)
  });

  // 10. no_data: empty state renders, block cards are hidden
  it('no_data state renders empty state card, not block cards', async () => {
    // systemStatus and summary errors + no checkpoints/HRV → hasAnySources = false → no_data
    vi.mocked(client.fetchSystemStatus).mockRejectedValue(new Error('offline'));
    vi.mocked(client.fetchSummary).mockRejectedValue(new Error('offline'));

    renderProgress();

    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());

    const chip = screen.getByTestId('progress-overall-state');
    expect(chip.getAttribute('data-state')).toBe('no_data');

    await waitFor(() => expect(screen.getByTestId('progress-empty')).toBeInTheDocument());
    // Block cards must be absent — they'd only show dashes with no data
    expect(screen.queryByTestId('progress-consistency')).toBeNull();
    expect(screen.queryByTestId('progress-signal')).toBeNull();
    expect(screen.queryByTestId('progress-confidence')).toBeNull();
  });

  // 11. limited state: empty state + DataConfidenceCard, no analytical block cards
  it('limited state renders DataConfidenceCard + empty state, not analytical cards', async () => {
    // Default: 0 checkpoints + 0 measurements → both blocks insufficient → limited
    renderProgress();

    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());

    const chip = screen.getByTestId('progress-overall-state');
    expect(chip.getAttribute('data-state')).toBe('limited');

    await waitFor(() => expect(screen.getByTestId('progress-empty')).toBeInTheDocument());
    expect(screen.getByTestId('progress-confidence')).toBeInTheDocument();
    expect(screen.queryByTestId('progress-consistency')).toBeNull();
    expect(screen.queryByTestId('progress-signal')).toBeNull();
  });

  // 12. sufficient/mixed: all block cards visible, no empty state
  it('sufficient state renders all block cards without empty state', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(10));
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      const readings: Array<[number, string]> =
        slug === 'hrv_rmssd'
          ? [[56, RECENT[0]], [56, RECENT[1]], [56, RECENT[2]], [48, PRIOR[0]], [48, PRIOR[1]], [48, PRIOR[2]]]
          : slug === 'resting_hr'
          ? [[60, RECENT[0]], [60, RECENT[1]], [60, RECENT[2]], [60, PRIOR[0]], [60, PRIOR[1]], [60, PRIOR[2]]]
          : [];
      return Promise.resolve(makeMeasurements(slug, 'ms', readings));
    });

    renderProgress();
    await waitFor(() => expect(screen.getByTestId('progress-consistency')).toBeInTheDocument());

    expect(screen.getByTestId('progress-signal')).toBeInTheDocument();
    expect(screen.getByTestId('progress-symptom')).toBeInTheDocument();
    expect(screen.getByTestId('progress-confidence')).toBeInTheDocument();
    expect(screen.queryByTestId('progress-empty')).toBeNull();
  });
});
