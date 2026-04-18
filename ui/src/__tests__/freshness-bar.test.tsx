import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FreshnessBar from '../components/FreshnessBar';
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
    fetchIllnessSignal: vi.fn(),
    fetchRecoveryStatus: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchActiveRegimens: vi.fn(),
    fetchSystemStatus: vi.fn(),
    createCheckpoint: vi.fn(),
    createSymptomLog: vi.fn(),
    createMedicationLog: vi.fn(),
    createMeasurement: vi.fn(),
    scanScale: vi.fn(),
  };
});

const USER_ID = 'test-user-id';

// Use local calendar dates so date-fns isToday/isYesterday comparisons work
// regardless of server timezone offset
function localDateISO(daysAgo = 0): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
const TODAY_LOCAL = localDateISO(0);
const YESTERDAY_LOCAL = localDateISO(1);

const emptyMeasurements = { items: [], total: 0, offset: 0, limit: 1 };
const emptyCheckpoints = { items: [], total: 0, offset: 0, limit: 14 };

// No trailing Z — treated as local time by parseISO, matching how the component
// calls .slice(0,10) and then date-fns isToday/isYesterday in local timezone
const garminMeasurement = {
  id: '1',
  user_id: USER_ID,
  metric_type_slug: 'hrv_rmssd',
  metric_type_name: 'HRV RMSSD',
  source_slug: 'garmin_connect',
  value_num: 45,
  unit: 'ms',
  measured_at: `${TODAY_LOCAL}T12:00:00`,
  aggregation_level: 'daily',
};

const scaleMeasurement = {
  id: '2',
  user_id: USER_ID,
  metric_type_slug: 'weight',
  metric_type_name: 'Weight',
  source_slug: 'hc900',
  value_num: 80,
  unit: 'kg',
  measured_at: `${YESTERDAY_LOCAL}T09:00:00`,
  aggregation_level: 'spot',
};

const morningCheckpoint = {
  id: '3',
  user_id: USER_ID,
  checkpoint_type: 'morning',
  checkpoint_date: TODAY_LOCAL,
  checkpoint_at: `${TODAY_LOCAL}T07:30:00`,
  mood: null,
  energy: null,
  sleep_quality: null,
  body_state_score: null,
  notes: null,
};

function renderFreshnessBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <FreshnessBar userId={USER_ID} />
    </QueryClientProvider>
  );
}

const emptySystemStatus = {
  user_id: USER_ID,
  sources: [] as import('../api/types').SystemSourceStatus[],
  agents: [] as import('../api/types').SystemAgentSummary[],
  as_of: new Date().toISOString(),
};

describe('FreshnessBar — per-source chips (A2)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(emptySystemStatus);
  });

  afterEach(() => vi.clearAllMocks());

  it('renders all three source labels', async () => {
    renderFreshnessBar();
    await waitFor(() => {
      expect(screen.getByText('Garmin last daily metric')).toBeInTheDocument();
      expect(screen.getByText('Scale')).toBeInTheDocument();
      expect(screen.getByText('Manual check-in')).toBeInTheDocument();
    });
  });

  it('shows "today" for Garmin when hrv_rmssd measured today', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'hrv_rmssd') {
        return Promise.resolve({ items: [garminMeasurement], total: 1, offset: 0, limit: 1 });
      }
      return Promise.resolve(emptyMeasurements);
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getAllByText('today').length).toBeGreaterThan(0));
  });

  it('shows "no data" for Garmin when no hrv_rmssd measurements', async () => {
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    renderFreshnessBar();
    // Both Garmin and Scale show "no data" when empty
    await waitFor(() => expect(screen.getAllByText('no data').length).toBeGreaterThanOrEqual(2));
  });

  it('shows "yesterday" for Scale when weight measured yesterday', async () => {
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'weight') {
        return Promise.resolve({ items: [scaleMeasurement], total: 1, offset: 0, limit: 1 });
      }
      return Promise.resolve(emptyMeasurements);
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('yesterday')).toBeInTheDocument());
  });

  it('shows "none today" for manual when no checkpoints today', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('none today')).toBeInTheDocument());
  });

  it('shows "morning" when morning checkpoint logged today', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({
      items: [morningCheckpoint],
      total: 1,
      offset: 0,
      limit: 14,
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('morning')).toBeInTheDocument());
  });

  it('shows "morning + night" when both logged today', async () => {
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({
      items: [
        morningCheckpoint,
        { ...morningCheckpoint, id: '4', checkpoint_type: 'night' },
      ],
      total: 2,
      offset: 0,
      limit: 14,
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('morning + night')).toBeInTheDocument());
  });
});

describe('FreshnessBar — Scan button', () => {
  beforeEach(() => {
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(emptySystemStatus);
  });
  afterEach(() => vi.clearAllMocks());

  it('renders Scan button next to Scale chip', async () => {
    renderFreshnessBar();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^scan$/i })).toBeInTheDocument()
    );
  });

  it('calls scanScale with userId when clicked', async () => {
    vi.mocked(client.scanScale).mockResolvedValue({ status: 'ok', message: 'Weight imported: 81.0 kg' });
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    expect(client.scanScale).toHaveBeenCalledWith(
      USER_ID,
      expect.any(AbortSignal),
      expect.any(Object),
      undefined,
    );
  });

  it('shows "Scanning… 45s" and disables button while pending', async () => {
    vi.mocked(client.scanScale).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    await waitFor(() => expect(screen.getByText(/Scanning… \d+s/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /scanning/i })).toBeDisabled();
  });

  it('shows cancel button while pending', async () => {
    vi.mocked(client.scanScale).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /cancel scan/i })).toBeInTheDocument());
  });

  it('restores Scan button after cancel', async () => {
    vi.mocked(client.scanScale).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    await waitFor(() => screen.getByRole('button', { name: /cancel scan/i }));
    await user.click(screen.getByRole('button', { name: /cancel scan/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^scan$/i })).toBeInTheDocument());
  });

  it('shows success message after scan completes', async () => {
    vi.mocked(client.scanScale).mockResolvedValue({ status: 'ok', message: 'Weight imported: 81.0 kg' });
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    await waitFor(() => expect(screen.getByText('Weight imported: 81.0 kg')).toBeInTheDocument());
  });

  it('shows error message when scan fails', async () => {
    vi.mocked(client.scanScale).mockRejectedValue(new Error('Scale not found'));
    const user = userEvent.setup();
    renderFreshnessBar();
    await waitFor(() => screen.getByRole('button', { name: /^scan$/i }));
    await user.click(screen.getByRole('button', { name: /^scan$/i }));
    await waitFor(() => expect(screen.getByText('Scale not found')).toBeInTheDocument());
  });
});

describe('FreshnessBar — B1 System Status (agents + source annotations)', () => {
  function localISO(daysAgo = 0): string {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T12:00:00`;
  }

  const TODAY_ISO = localISO(0);
  const YESTERDAY_ISO = localISO(1);

  beforeEach(() => {
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(emptySystemStatus);
  });

  afterEach(() => vi.clearAllMocks());

  it('B1-F1: renders agent display_name when system status has agents', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...emptySystemStatus,
      agents: [
        {
          agent_type: 'local_pc',
          display_name: 'Desktop',
          status: 'active',
          last_seen_at: TODAY_ISO,
        },
      ],
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('Desktop')).toBeInTheDocument());
  });

  it('B1-F2: falls back to agent_type when display_name is null', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...emptySystemStatus,
      agents: [
        {
          agent_type: 'local_pc',
          display_name: null,
          status: 'stale',
          last_seen_at: YESTERDAY_ISO,
        },
      ],
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText('local_pc')).toBeInTheDocument());
  });

  it('B1-F3: Garmin sync annotation appears when last_sync_at is set', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...emptySystemStatus,
      sources: [
        {
          source_slug: 'garmin_connect',
          integration_configured: true,
          device_paired: null,
          last_sync_at: YESTERDAY_ISO,
          last_advanced_at: null,
          last_run_status: 'completed',
          last_run_at: YESTERDAY_ISO,
        },
      ],
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText(/sync yesterday/i)).toBeInTheDocument());
  });

  it('B1-F4: Garmin data annotation shows last_advanced_at when present', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...emptySystemStatus,
      sources: [
        {
          source_slug: 'garmin_connect',
          integration_configured: true,
          device_paired: null,
          last_sync_at: YESTERDAY_ISO,
          last_advanced_at: TODAY_ISO,
          last_run_status: 'completed',
          last_run_at: YESTERDAY_ISO,
        },
      ],
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText(/data today/i)).toBeInTheDocument());
  });

  it('B1-F5: HC900 "no device" annotation when device_paired is false', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...emptySystemStatus,
      sources: [
        {
          source_slug: 'hc900_ble',
          integration_configured: true,
          device_paired: false,
          last_sync_at: null,
          last_advanced_at: null,
          last_run_status: null,
          last_run_at: null,
        },
      ],
    });
    renderFreshnessBar();
    await waitFor(() => expect(screen.getByText(/no device/i)).toBeInTheDocument());
  });
});
