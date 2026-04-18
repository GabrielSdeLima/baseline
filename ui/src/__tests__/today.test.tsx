import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Today from '../pages/Today';
import * as client from '../api/client';

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchSummary: vi.fn(),
    fetchDeviations: vi.fn(),
    fetchMedicationAdherence: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchCheckpoints: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    fetchSystemStatus: vi.fn(),
    fetchIllnessSignal: vi.fn(),
    fetchRecoveryStatus: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchActiveRegimens: vi.fn(),
    createCheckpoint: vi.fn(),
    createSymptomLog: vi.fn(),
    createMedicationLog: vi.fn(),
    createMeasurement: vi.fn(),
  };
});

const USER_ID = 'test-user-id';
const TODAY = new Date().toISOString().slice(0, 10);

// ── Default fixtures ───────────────────────────────────────────────────────

const OK_BLOCK = {
  deviations: 'ok' as const,
  illness: 'ok' as const,
  recovery: 'ok' as const,
  adherence: 'ok' as const,
  symptoms: 'ok' as const,
};

const defaultSummary = {
  user_id: USER_ID,
  as_of: TODAY,
  overall_adherence_pct: 85 as unknown as number,
  active_deviations: 0,
  current_symptom_burden: '0' as unknown as number,
  illness_signal: 'low',
  recovery_status: 'recovered',
  block_availability: OK_BLOCK,
  data_availability: null,
};

const defaultDeviations = {
  user_id: USER_ID,
  baseline_window_days: 14,
  deviation_threshold: 2.0 as unknown as number,
  deviations: [],
  metrics_flagged: 0,
  availability_status: 'ok' as const,
  data_availability: null,
};

const defaultAdherence = {
  user_id: USER_ID,
  items: [
    {
      medication_name: 'Vitamin D', frequency: 'daily',
      taken: 8, skipped: 0, delayed: 0, total: 10,
      adherence_pct: 80 as unknown as number,
      item_status: 'ok' as const,
    },
  ],
  overall_adherence_pct: '80' as unknown as number,
  availability_status: 'ok' as const,
};

const emptyList = { items: [], total: 0, offset: 0, limit: 1 };

const neverMeasuredScale = {
  status: 'never_measured' as const,
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};

function renderToday() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Today />
    </QueryClientProvider>
  );
  return qc;
}

function setupDefaults() {
  vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
  vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
  vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
  vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
  vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
  vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  vi.mocked(client.fetchSystemStatus).mockResolvedValue({
    user_id: USER_ID,
    sources: [],
    agents: [],
    as_of: new Date().toISOString(),
  });
}

// ── B1. Symptom Burden ────────────────────────────────────────────────────

describe('Today — Symptom Burden (B1)', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  it('shows "No symptoms today" when backend returns burden as string "0"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      current_symptom_burden: '0' as unknown as number,
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('No symptoms today')).toBeInTheDocument());
  });

  it('shows burden value when > 0', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      current_symptom_burden: '3.5' as unknown as number,
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('Burden: 3.5')).toBeInTheDocument());
  });
});

// ── B2. Medication Adherence ──────────────────────────────────────────────

describe('Today — Medication Adherence (B2)', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  it('shows "No active regimens" when availability_status is not_applicable', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: USER_ID,
      items: [],
      overall_adherence_pct: null,
      availability_status: 'not_applicable',
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('No active regimens')).toBeInTheDocument());
  });

  it('shows adherence percentage when items exist', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
    renderToday();
    await waitFor(() => expect(screen.getByText('80% overall')).toBeInTheDocument());
  });

  it('shows 0% overall when items exist but all skipped', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: USER_ID,
      items: [
        {
          medication_name: 'Test', frequency: 'daily',
          taken: 0, skipped: 5, delayed: 0, total: 5,
          adherence_pct: 0,
          item_status: 'ok' as const,
        },
      ],
      overall_adherence_pct: '0.0' as unknown as number,
      availability_status: 'ok',
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('0% overall')).toBeInTheDocument());
  });
});

// ── A3. Deviations / Baseline ─────────────────────────────────────────────

describe('Today — Deviations / Baseline Forming (A3)', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  it('shows "Baseline still forming" when block_availability.deviations is insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      block_availability: { ...OK_BLOCK, deviations: 'insufficient_data' },
    });
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 2, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    renderToday();
    await waitFor(() => expect(screen.getByText(/Baseline still forming/i)).toBeInTheDocument());
  });

  it('shows hrv count when block_availability.deviations is insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      block_availability: { ...OK_BLOCK, deviations: 'insufficient_data' },
    });
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 1, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    renderToday();
    await waitFor(() => expect(screen.getByText(/1 of 3 HRV readings/i)).toBeInTheDocument());
  });

  it('shows "All metrics within baseline" when deviations=ok and active_deviations=0', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 10, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    vi.mocked(client.fetchSummary).mockResolvedValue({ ...defaultSummary, active_deviations: 0 });
    renderToday();
    await waitFor(() => expect(screen.getByText('All metrics within baseline')).toBeInTheDocument());
  });

  it('shows metric count when deviations exist and block=ok', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 10, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    vi.mocked(client.fetchSummary).mockResolvedValue({ ...defaultSummary, active_deviations: 2 });
    renderToday();
    await waitFor(() => expect(screen.getByText('2 metrics outside baseline')).toBeInTheDocument());
  });
});

// ── A2. FreshnessBar ──────────────────────────────────────────────────────

describe('Today — FreshnessBar (A2)', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  it('renders all three source chips in FreshnessBar', async () => {
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('Garmin last daily metric')).toBeInTheDocument();
      expect(screen.getByText('Scale')).toBeInTheDocument();
      expect(screen.getByText('Manual check-in')).toBeInTheDocument();
    });
  });
});

// ── Illness / Recovery insufficient (legacy) ──────────────────────────────

describe('Today — Illness / Insufficient data', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  it('shows availability label for illness when block=insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      illness_signal: 'insufficient_data',
      block_availability: { ...OK_BLOCK, illness: 'insufficient_data' },
    });
    renderToday();
    await waitFor(() =>
      expect(screen.getByText('Baseline still forming')).toBeInTheDocument()
    );
  });

  it('shows availability label for recovery when block=insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      recovery_status: 'insufficient_data',
      block_availability: { ...OK_BLOCK, recovery: 'insufficient_data' },
    });
    renderToday();
    await waitFor(() =>
      expect(screen.getAllByText('Baseline still forming').length).toBeGreaterThan(0)
    );
  });
});

// ── B6. Availability Wiring ───────────────────────────────────────────────

describe('Today — B6 Availability Wiring', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  // 1. deviations no_data → no all-clear
  it('B6-1: deviations no_data — does not show "All metrics within baseline"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      active_deviations: 0,
      block_availability: { ...OK_BLOCK, deviations: 'no_data' },
    });
    renderToday();
    await waitFor(() => {
      expect(screen.queryByText('All metrics within baseline')).not.toBeInTheDocument();
      expect(screen.getByText('No physiological data yet')).toBeInTheDocument();
    });
  });

  // 2. deviations no_data_today
  it('B6-2: deviations no_data_today — shows "No data for today"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      active_deviations: 0,
      block_availability: { ...OK_BLOCK, deviations: 'no_data_today' },
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('No data for today')).toBeInTheDocument());
  });

  // 3. deviations insufficient_data
  it('B6-3: deviations insufficient_data — shows "Baseline still forming"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      block_availability: { ...OK_BLOCK, deviations: 'insufficient_data' },
    });
    renderToday();
    await waitFor(() => expect(screen.getByText(/Baseline still forming/i)).toBeInTheDocument());
  });

  // 4. illness partial — shows badge with "partial coverage" caveat
  it('B6-4: illness partial — renders badge and partial-coverage caveat', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      illness_signal: 'low',
      block_availability: { ...OK_BLOCK, illness: 'partial' },
    });
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('partial coverage')).toBeInTheDocument();
    });
  });

  // 5a. recovery no_data_today — no badge shown
  it('B6-5a: recovery no_data_today — shows "No data for today" instead of badge', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      recovery_status: 'recovered',
      block_availability: { ...OK_BLOCK, recovery: 'no_data_today' },
    });
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('No data for today')).toBeInTheDocument();
    });
  });

  // 5b. recovery stale_data
  it('B6-5b: recovery stale_data — shows "Data is stale"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      recovery_status: 'recovered',
      block_availability: { ...OK_BLOCK, recovery: 'stale_data' },
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('Data is stale')).toBeInTheDocument());
  });

  // 6. medication not_applicable
  it('B6-6: medication not_applicable — shows "No active regimens"', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: USER_ID,
      items: [],
      overall_adherence_pct: null,
      availability_status: 'not_applicable',
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('No active regimens')).toBeInTheDocument());
  });

  // 7. medication partial + pending_first_log → no percentage shown
  it('B6-7: medication partial (pending_first_log) — shows waiting message, not 0%', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: USER_ID,
      items: [
        {
          medication_name: 'Omega-3', frequency: 'daily',
          taken: 0, skipped: 0, delayed: 0, total: 0,
          adherence_pct: null,
          item_status: 'pending_first_log' as const,
        },
      ],
      overall_adherence_pct: null,
      availability_status: 'partial',
    });
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('Regimen active, waiting for first log')).toBeInTheDocument();
      expect(screen.queryByText(/% overall/)).not.toBeInTheDocument();
    });
  });

  // 8. symptoms not_applicable (tracking never used)
  it('B6-8: symptoms not_applicable — shows "Symptom tracking not started", not "No symptoms today"', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      current_symptom_burden: '0' as unknown as number,
      block_availability: { ...OK_BLOCK, symptoms: 'not_applicable' },
    });
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('Symptom tracking not started')).toBeInTheDocument();
      expect(screen.queryByText('No symptoms today')).not.toBeInTheDocument();
    });
  });

  // 9. symptoms ok with burden 0 — quiet day is legitimate
  it('B6-9: symptoms ok with burden 0 — shows "No symptoms today" (tracking was used)', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      current_symptom_burden: '0' as unknown as number,
      block_availability: { ...OK_BLOCK, symptoms: 'ok' },
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('No symptoms today')).toBeInTheDocument());
  });

  // 10. all blocks ok — full healthy render
  it('B6-10: all blocks ok — renders badge, percentage, and all-clear deviations', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      illness_signal: 'low',
      recovery_status: 'recovered',
      active_deviations: 0,
      current_symptom_burden: '0' as unknown as number,
      overall_adherence_pct: 95,
      block_availability: OK_BLOCK,
    });
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      ...defaultAdherence,
      overall_adherence_pct: '95' as unknown as number,
      availability_status: 'ok',
    });
    renderToday();
    await waitFor(() => {
      expect(screen.getByText('All metrics within baseline')).toBeInTheDocument();
      expect(screen.getByText('95% overall')).toBeInTheDocument();
      expect(screen.getByText('No symptoms today')).toBeInTheDocument();
    });
  });
});
