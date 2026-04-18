/**
 * Closes the loop on the user-facing requirement:
 *   "scale-latest invalidates correctly after Scan"
 *   "Home reflects the new reading without manual refresh"
 *
 * The test mounts Today, waits for the initial `never_measured` state to
 * render, triggers the Scan button in FreshnessBar, and then flips the
 * mock to return a full_reading.  If invalidation fires correctly,
 * react-query refetches and the card updates in-place — no reload.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Today from '../pages/Today';
import * as client from '../api/client';
import type { LatestScaleReading } from '../api/types';

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../lib/scaleProfile', () => ({
  loadScaleProfile: () => ({ height_cm: 180, birth_date: '1991-08-15', sex: 1 }),
  saveScaleProfile: vi.fn(),
}));

vi.mock('../lib/scaleDevice', () => ({
  loadScaleDevice: () => ({ mac: 'A0:91:5C:92:CF:17' }),
  saveScaleDevice: vi.fn(),
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
    scanScale: vi.fn(),
  };
});

const NEVER: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};

const FULL: LatestScaleReading = {
  status: 'full_reading',
  measured_at: new Date(Date.now() - 60_000).toISOString(),
  raw_payload_id: '019d9908-aaaa-7777-8888-999999999999',
  decoder_version: 'hc900_ble_v2',
  has_impedance: true,
  metrics: {
    weight: { slug: 'weight', value: '78.12', unit: 'kg', is_derived: false },
    impedance_adc: { slug: 'impedance_adc', value: '530', unit: 'adc', is_derived: false },
    bmi: { slug: 'bmi', value: '24.1', unit: 'kg/m²', is_derived: true },
    bmr: { slug: 'bmr', value: '1725', unit: 'kcal', is_derived: true },
    body_fat_pct: { slug: 'body_fat_pct', value: '22.0', unit: '%', is_derived: true },
    muscle_pct: { slug: 'muscle_pct', value: '50.0', unit: '%', is_derived: true },
    water_pct: { slug: 'water_pct', value: '56.5', unit: '%', is_derived: true },
  },
};

const emptyList = { items: [], total: 0, offset: 0, limit: 1 };
const defaultSummary = {
  user_id: 'test-user-id',
  as_of: '2026-04-16',
  overall_adherence_pct: 80 as unknown as number,
  active_deviations: 0,
  current_symptom_burden: '0' as unknown as number,
  illness_signal: 'low',
  recovery_status: 'recovered',
  block_availability: {
    deviations: 'ok' as const,
    illness: 'ok' as const,
    recovery: 'ok' as const,
    adherence: 'ok' as const,
    symptoms: 'ok' as const,
  },
  data_availability: null,
};

function renderWithQC() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Today />
    </QueryClientProvider>
  );
  return qc;
}

describe('Scan → scale-latest invalidation → auto-refresh', () => {
  beforeEach(() => {
    vi.mocked(client.fetchSummary).mockResolvedValue(defaultSummary);
    vi.mocked(client.fetchDeviations).mockResolvedValue({
      user_id: 'test-user-id',
      baseline_window_days: 14,
      deviation_threshold: 2.0 as unknown as number,
      deviations: [],
      metrics_flagged: 0,
      availability_status: 'ok' as const,
      data_availability: null,
    });
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue({
      user_id: 'test-user-id',
      items: [],
      overall_adherence_pct: null,
      availability_status: 'not_applicable' as const,
    });
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ ...emptyList, total: 10 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      user_id: 'test-user-id',
      sources: [],
      agents: [],
      as_of: new Date().toISOString(),
    });
    vi.mocked(client.scanScale).mockResolvedValue({ status: 'ok', message: 'Import complete' });
  });

  afterEach(() => vi.clearAllMocks());

  it('card updates from never_measured → full_reading after Scan, no reload', async () => {
    // Initially no readings
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(NEVER);
    renderWithQC();

    await waitFor(() =>
      expect(screen.getByText(/No readings yet/i)).toBeInTheDocument()
    );

    // After a successful scan, the server has a new full_reading
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(FULL);

    // Click the Scan button in FreshnessBar
    const scanBtn = screen.getByRole('button', { name: /scan/i });
    await userEvent.click(scanBtn);

    // Mutation succeeds → invalidation fires → card refetches → new data renders
    await waitFor(() =>
      expect(screen.getByText('78.12')).toBeInTheDocument()
    );
    expect(screen.getByText('Body fat')).toBeInTheDocument();
    expect(screen.getByText('22.0')).toBeInTheDocument();
    expect(screen.queryByText(/No readings yet/i)).not.toBeInTheDocument();
  });
});
