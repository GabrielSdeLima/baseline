import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import QuickInputModal from '../components/QuickInputModal';
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

const sampleRegimen = {
  id: 'regimen-1',
  user_id: USER_ID,
  medication_id: 1,
  medication_name: 'Vitamin D',
  dosage_amount: 1000,
  dosage_unit: 'IU',
  frequency: 'daily',
  instructions: null,
  prescribed_by: null,
  started_at: '2026-01-01',
  ended_at: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function renderModal(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
  render(
    <QueryClientProvider client={qc}>
      <QuickInputModal onClose={onClose} />
    </QueryClientProvider>
  );
  return { qc, invalidateSpy };
}

describe('Quick Input — No weight in Measure tab (A1)', () => {
  afterEach(() => vi.clearAllMocks());

  it('Measure tab has body_temperature but not weight', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /measure/i }));
    // body_temperature present
    expect(screen.getByText('Body Temperature')).toBeInTheDocument();
    // weight not present in the select
    const options = screen.queryAllByRole('option');
    const labels = options.map((o) => o.textContent);
    expect(labels).not.toContain('Weight');
    expect(labels.some((l) => l?.includes('Body Temperature'))).toBe(true);
  });
});

describe('Quick Input — Symptom started_at collapsible (Q1)', () => {
  afterEach(() => vi.clearAllMocks());

  it('shows "edit time" link by default, hides datetime input', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /symptom/i }));
    expect(screen.getByText('edit time')).toBeInTheDocument();
    expect(screen.queryByText('use now')).not.toBeInTheDocument();
  });

  it('shows datetime input after clicking "edit time"', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /symptom/i }));
    await user.click(screen.getByText('edit time'));
    expect(screen.getByText('use now')).toBeInTheDocument();
    expect(screen.queryByText('edit time')).not.toBeInTheDocument();
  });

  it('collapses back when clicking "use now"', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /symptom/i }));
    await user.click(screen.getByText('edit time'));
    await user.click(screen.getByText('use now'));
    expect(screen.getByText('edit time')).toBeInTheDocument();
  });
});

describe('Quick Input — Checkpoint ScoreRow order by type (Q2)', () => {
  afterEach(() => vi.clearAllMocks());

  it('morning checkpoint shows Sleep quality, Energy, Mood', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /morning/i }));
    // All three labels present
    expect(screen.getByText('Sleep quality')).toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.getByText('Mood')).toBeInTheDocument();
  });

  it('night checkpoint does NOT show Sleep quality', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /night/i }));
    expect(screen.queryByText('Sleep quality')).not.toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.getByText('Mood')).toBeInTheDocument();
  });
});

describe('Quick Input — Med Log empty state (E1)', () => {
  beforeEach(() => {
    vi.mocked(client.fetchActiveRegimens).mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 50,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it('shows useful empty state pointing to Meds tab', async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole('button', { name: /med log/i }));
    await waitFor(() => {
      expect(screen.getByText(/No active medication regimens/i)).toBeInTheDocument();
      expect(screen.getByText(/Meds/)).toBeInTheDocument();
    });
  });
});

describe('Quick Input — Cache invalidation of summary after mutations (B3)', () => {
  afterEach(() => vi.clearAllMocks());

  it('checkpoint submit invalidates summary and checkpoints', async () => {
    const user = userEvent.setup();
    vi.mocked(client.createCheckpoint).mockResolvedValue({});
    const { invalidateSpy } = renderModal();

    // Checkpoint tab is default
    await user.click(screen.getByRole('button', { name: /save checkpoint/i }));

    await waitFor(() => {
      const calls = invalidateSpy.mock.calls.map((c) => JSON.stringify(c[0]));
      expect(calls.some((c) => c.includes('"summary"'))).toBe(true);
      expect(calls.some((c) => c.includes('"checkpoints"'))).toBe(true);
    });
  });

  it('symptom submit invalidates summary and symptomLogs', async () => {
    const user = userEvent.setup();
    vi.mocked(client.createSymptomLog).mockResolvedValue({});
    const { invalidateSpy } = renderModal();

    await user.click(screen.getByRole('button', { name: /symptom/i }));
    await user.click(screen.getByRole('button', { name: /log symptom/i }));

    await waitFor(() => {
      const calls = invalidateSpy.mock.calls.map((c) => JSON.stringify(c[0]));
      expect(calls.some((c) => c.includes('"summary"'))).toBe(true);
      expect(calls.some((c) => c.includes('"symptomLogs"'))).toBe(true);
    });
  });

  it('measurement submit invalidates summary and measurements', async () => {
    const user = userEvent.setup();
    vi.mocked(client.createMeasurement).mockResolvedValue({});
    const { invalidateSpy } = renderModal();

    await user.click(screen.getByRole('button', { name: /measure/i }));
    // Fill in a value (required field)
    await user.type(screen.getByRole('spinbutton'), '37.2');
    await user.click(screen.getByRole('button', { name: /save measurement/i }));

    await waitFor(() => {
      const calls = invalidateSpy.mock.calls.map((c) => JSON.stringify(c[0]));
      expect(calls.some((c) => c.includes('"summary"'))).toBe(true);
      expect(calls.some((c) => c.includes('"measurements"'))).toBe(true);
    });
  });

  it('med log submit invalidates summary and adherence', async () => {
    const user = userEvent.setup();
    vi.mocked(client.fetchActiveRegimens).mockResolvedValue({
      items: [sampleRegimen],
      total: 1,
      offset: 0,
      limit: 50,
    });
    vi.mocked(client.createMedicationLog).mockResolvedValue({});
    const { invalidateSpy } = renderModal();

    await user.click(screen.getByRole('button', { name: /med log/i }));
    await waitFor(() => expect(screen.getByText('Vitamin D — 1000 IU')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /log medication/i }));

    await waitFor(() => {
      const calls = invalidateSpy.mock.calls.map((c) => JSON.stringify(c[0]));
      expect(calls.some((c) => c.includes('"summary"'))).toBe(true);
      expect(calls.some((c) => c.includes('"adherence"'))).toBe(true);
    });
  });
});
