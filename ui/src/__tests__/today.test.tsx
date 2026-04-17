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

const defaultSummary = {
  user_id: USER_ID,
  as_of: TODAY,
  overall_adherence_pct: 85 as unknown as number,
  active_deviations: 0,
  current_symptom_burden: '0' as unknown as number,
  illness_signal: 'low',
  recovery_status: 'recovered',
};

const defaultDeviations = {
  user_id: USER_ID,
  baseline_window_days: 14,
  deviation_threshold: 2.0 as unknown as number,
  deviations: [],
  metrics_flagged: 0,
};

const defaultAdherence = {
  user_id: USER_ID,
  items: [
    { medication_name: 'Vitamin D', frequency: 'daily', taken: 8, skipped: 0, delayed: 0, total: 10, adherence_pct: 80 as unknown as number },
  ],
  overall_adherence_pct: '80' as unknown as number,
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

describe('Today — Symptom Burden (B1)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
    vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  });

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

describe('Today — Medication Adherence (B2)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
    vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  });

  afterEach(() => vi.clearAllMocks());

  it('shows "No active regimens" when adherence items array is empty', async () => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: USER_ID,
      items: [],
      overall_adherence_pct: 0,
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
      items: [{ medication_name: 'Test', frequency: 'daily', taken: 0, skipped: 5, delayed: 0, total: 5, adherence_pct: 0 }],
      overall_adherence_pct: '0.0' as unknown as number,
    });
    renderToday();
    await waitFor(() => expect(screen.getByText('0% overall')).toBeInTheDocument());
  });
});

describe('Today — Deviations / Baseline Forming (A3)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
    vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  });

  afterEach(() => vi.clearAllMocks());

  it('shows "Baseline forming" when hrv measurement count < 3', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 2, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    renderToday();
    await waitFor(() => expect(screen.getByText(/Baseline forming/i)).toBeInTheDocument());
  });

  it('shows hrv count when baseline forming', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 1, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    renderToday();
    await waitFor(() => expect(screen.getByText(/1 of 3 HRV readings/i)).toBeInTheDocument());
  });

  it('shows "All metrics within baseline" when baseline established and no deviations', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 10, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    vi.mocked(client.fetchSummary).mockResolvedValue({ ...defaultSummary, active_deviations: 0 });
    renderToday();
    await waitFor(() => expect(screen.getByText('All metrics within baseline')).toBeInTheDocument());
  });

  it('shows metric count when deviations exist', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, _slug, limit) => {
      if (limit === 14) return Promise.resolve({ items: [], total: 10, offset: 0, limit: 14 });
      return Promise.resolve(emptyList);
    });
    vi.mocked(client.fetchSummary).mockResolvedValue({ ...defaultSummary, active_deviations: 2 });
    renderToday();
    await waitFor(() => expect(screen.getByText('2 metrics outside baseline')).toBeInTheDocument());
  });
});

describe('Today — FreshnessBar (A2)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
    vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  });

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

describe('Today — Illness / Insufficient data', () => {
  beforeEach(() => {
    vi.mocked(client.fetchDeviations).mockResolvedValue(defaultDeviations);
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  });

  afterEach(() => vi.clearAllMocks());

  it('shows "establishing baseline" note for illness_signal insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      illness_signal: 'insufficient_data',
    });
    renderToday();
    await waitFor(() =>
      expect(screen.getAllByText(/establishing baseline/i).length).toBeGreaterThan(0)
    );
  });

  it('shows "establishing baseline" note for recovery_status insufficient_data', async () => {
    vi.mocked(client.fetchSummary).mockResolvedValue({
      ...defaultSummary,
      recovery_status: 'insufficient_data',
    });
    renderToday();
    await waitFor(() =>
      expect(screen.getAllByText(/establishing baseline/i).length).toBeGreaterThan(0)
    );
  });
});
