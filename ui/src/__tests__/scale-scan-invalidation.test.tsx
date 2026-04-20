/**
 * Closes the loop on the user-facing requirement:
 *   "scale-latest invalidates correctly after Scan"
 *   "Today reflects the new reading without manual refresh"
 *
 * In Today v2 the scale scan is triggered from the "Weigh in" action in the
 * priority list. After the scan succeeds the today-v2 queries are invalidated;
 * react-query refetches and the weight completion flips from missing → complete.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Today from '../pages/Today';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  LatestScaleReading,
  MeasurementList,
  MedicationAdherenceResponse,
  MedicationRegimenList,
  SymptomLogList,
  SystemStatusResponse,
} from '../api/types';

const DATE = '2026-04-17';
const NOW = '2026-04-17T18:00:00.000Z';

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
    todayISO: () => DATE,
    nowISO: () => NOW,
    fetchMedicationAdherence: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    fetchActiveRegimens: vi.fn(),
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
  measured_at: `${DATE}T17:30:00.000Z`,
  raw_payload_id: '019d9908-aaaa-7777-8888-999999999999',
  decoder_version: 'hc900_ble_v2',
  has_impedance: true,
  metrics: {
    weight: { slug: 'weight', value: '78.12', unit: 'kg', is_derived: false },
  },
};

const emptyMeasurements: MeasurementList = { items: [], total: 0, offset: 0, limit: 1 };
const emptyCheckpoints: DailyCheckpointList = { items: [], total: 0, offset: 0, limit: 14 };
const emptySymptoms: SymptomLogList = { items: [], total: 0, offset: 0, limit: 50 };
const emptyRegimens: MedicationRegimenList = { items: [], total: 0, offset: 0, limit: 1 };
const emptyAdherence: MedicationAdherenceResponse = {
  user_id: 'test-user-id',
  items: [],
  overall_adherence_pct: null,
  availability_status: 'not_applicable',
};
const defaultSystemStatus: SystemStatusResponse = {
  user_id: 'test-user-id',
  sources: [
    {
      source_slug: 'garmin_connect',
      integration_configured: true,
      device_paired: null,
      last_sync_at: NOW,
      last_advanced_at: NOW,
      last_run_status: 'ok',
      last_run_at: NOW,
    },
    {
      source_slug: 'hc900_ble',
      integration_configured: true,
      device_paired: true,
      last_sync_at: NOW,
      last_advanced_at: NOW,
      last_run_status: 'ok',
      last_run_at: NOW,
    },
  ],
  agents: [],
  as_of: NOW,
};

const weightAfter: MeasurementList = {
  items: [
    {
      id: 'm-weight-after-scan',
      user_id: 'test-user-id',
      metric_type_slug: 'weight',
      metric_type_name: 'Weight',
      source_slug: 'hc900_ble',
      value_num: 78.12,
      unit: 'kg',
      measured_at: `${DATE}T17:30:00.000Z`,
      aggregation_level: 'raw',
    },
  ],
  total: 1,
  offset: 0,
  limit: 5,
};

function renderWithQC() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Today onOpenInput={vi.fn()} />
    </QueryClientProvider>,
  );
  return qc;
}

describe('Scan → today-v2 invalidation → auto-refresh', () => {
  beforeEach(() => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(emptyAdherence);
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms);
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(NEVER);
    vi.mocked(client.fetchActiveRegimens).mockResolvedValue(emptyRegimens);
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(defaultSystemStatus);
    vi.mocked(client.scanScale).mockResolvedValue({ status: 'ok', message: 'Import complete' });
  });

  afterEach(() => vi.clearAllMocks());

  it('weight completion flips from missing → complete after Weigh in action', async () => {
    renderWithQC();

    // Before scan: weight completion is missing
    await waitFor(() => expect(screen.getByTestId('today-completion')).toBeInTheDocument());
    const completion = screen.getByTestId('today-completion');
    expect(completion.textContent).toMatch(/weight\s*pending/i);

    // After scan, the backend has a weight measurement today
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'weight') return Promise.resolve(weightAfter);
      return Promise.resolve(emptyMeasurements);
    });
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(FULL);

    // Click Weigh in — surfaces from the priority list.
    const weighLabel = screen.getByText(/^Weigh in$/);
    const weighItem = weighLabel.closest('li');
    expect(weighItem).not.toBeNull();
    const doBtn = weighItem!.querySelector('button');
    expect(doBtn).not.toBeNull();
    fireEvent.click(doBtn!);

    await waitFor(() => expect(vi.mocked(client.scanScale)).toHaveBeenCalledTimes(1));

    // Invalidation refetches today-v2.measurements.weight → weight becomes complete.
    await waitFor(() => {
      const node = screen.getByTestId('today-completion');
      expect(node.textContent).toMatch(/weight\s*done/i);
    });
  });
});
