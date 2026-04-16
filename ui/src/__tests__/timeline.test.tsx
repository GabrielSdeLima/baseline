import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Timeline from '../pages/Timeline';
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
    createCheckpoint: vi.fn(),
    createSymptomLog: vi.fn(),
    createMedicationLog: vi.fn(),
    createMeasurement: vi.fn(),
  };
});

const USER_ID = 'test-user-id';

const emptyIllness = {
  user_id: USER_ID,
  method: 'baseline_deviation_v1',
  days: [],
  peak_signal: 'insufficient_data',
  peak_signal_date: null,
};

const emptyRecovery = {
  user_id: USER_ID,
  method: 'load_hrv_heuristic_v1',
  days: [],
  current_status: 'insufficient_data',
};

function renderTimeline() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Timeline />
    </QueryClientProvider>
  );
  return qc;
}

describe('Timeline — table and legend (E2)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchIllnessSignal).mockResolvedValue(emptyIllness);
    vi.mocked(client.fetchRecoveryStatus).mockResolvedValue(emptyRecovery);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 7 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  });

  afterEach(() => vi.clearAllMocks());

  it('renders legend "– no reading for that day"', async () => {
    renderTimeline();
    await waitFor(() =>
      expect(screen.getByText('– no reading for that day')).toBeInTheDocument()
    );
  });

  it('renders all six column headers', async () => {
    renderTimeline();
    await waitFor(() => {
      expect(screen.getByText('Date')).toBeInTheDocument();
      expect(screen.getByText('HRV')).toBeInTheDocument();
      expect(screen.getByText('Illness')).toBeInTheDocument();
      expect(screen.getByText('Recovery')).toBeInTheDocument();
      expect(screen.getByText('Symptoms')).toBeInTheDocument();
      expect(screen.getByText('Check-in')).toBeInTheDocument();
    });
  });

  it('renders 7 data rows', async () => {
    renderTimeline();
    await waitFor(() => {
      // 7 rows in tbody; each row has a date cell with "today" marker on one of them
      const rows = screen.getAllByRole('row');
      // 1 header row + 7 data rows
      expect(rows.length).toBe(8);
    });
  });

  it('shows "today" marker on today row', async () => {
    renderTimeline();
    await waitFor(() => expect(screen.getByText('·today')).toBeInTheDocument());
  });

  it('shows "Last 7 days" heading', async () => {
    renderTimeline();
    await waitFor(() => expect(screen.getByText('Last 7 days')).toBeInTheDocument());
  });
});

describe('Timeline — week navigation', () => {
  beforeEach(() => {
    vi.mocked(client.fetchIllnessSignal).mockResolvedValue(emptyIllness);
    vi.mocked(client.fetchRecoveryStatus).mockResolvedValue(emptyRecovery);
    vi.mocked(client.fetchMeasurements).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 7 });
    vi.mocked(client.fetchCheckpoints).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 14 });
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
  });
  afterEach(() => vi.clearAllMocks());

  it('renders Prev and Next buttons', async () => {
    renderTimeline();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /prev/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument();
    });
  });

  it('Next button is disabled on current week', async () => {
    renderTimeline();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
    );
  });

  it('Prev shifts to date range label (not "Last 7 days")', async () => {
    const user = userEvent.setup();
    renderTimeline();
    await waitFor(() => screen.getByRole('button', { name: /prev/i }));
    await user.click(screen.getByRole('button', { name: /prev/i }));
    await waitFor(() =>
      expect(screen.queryByText('Last 7 days')).not.toBeInTheDocument()
    );
    // date range label like "Apr 1 – Apr 7" should appear
    expect(screen.getByText(/\w{3} \d+ – \w{3} \d+/)).toBeInTheDocument();
  });

  it('Next becomes enabled after going back, restores "Last 7 days" after clicking Next', async () => {
    const user = userEvent.setup();
    renderTimeline();
    await waitFor(() => screen.getByRole('button', { name: /prev/i }));
    await user.click(screen.getByRole('button', { name: /prev/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /next/i })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(screen.getByText('Last 7 days')).toBeInTheDocument());
  });

  it('does not show ·today marker when viewing a past week', async () => {
    const user = userEvent.setup();
    renderTimeline();
    await waitFor(() => screen.getByRole('button', { name: /prev/i }));
    await user.click(screen.getByRole('button', { name: /prev/i }));
    await waitFor(() => expect(screen.queryByText('·today')).not.toBeInTheDocument());
  });
});
