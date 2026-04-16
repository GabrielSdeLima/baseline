import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Medications from '../pages/Medications';
import * as client from '../api/client';

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchAllRegimens: vi.fn(),
    fetchMedicationDefinitions: vi.fn(),
    createMedicationDefinition: vi.fn(),
    createMedicationRegimen: vi.fn(),
    createMedicationLog: vi.fn(),
    deactivateRegimen: vi.fn(),
  };
});

const USER_ID = 'test-user-id';

const emptyRegimens = { items: [], total: 0, offset: 0, limit: 50 };

const activeRegimen = {
  id: 'reg-1',
  user_id: USER_ID,
  medication_id: 1,
  medication_name: 'Omeprazole 20mg',
  dosage_amount: 20,
  dosage_unit: 'mg',
  frequency: 'daily',
  instructions: 'take with food',
  prescribed_by: null,
  started_at: '2026-01-01',
  ended_at: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
};

const pastRegimen = {
  ...activeRegimen,
  id: 'reg-2',
  medication_name: 'Ibuprofen 400mg',
  ended_at: '2026-02-15',
  is_active: false,
};

function renderMedications() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Medications />
    </QueryClientProvider>
  );
}

describe('Medications — empty state', () => {
  beforeEach(() => {
    vi.mocked(client.fetchAllRegimens).mockResolvedValue(emptyRegimens);
    vi.mocked(client.fetchMedicationDefinitions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('renders heading and Add regimen button', async () => {
    renderMedications();
    await waitFor(() => {
      expect(screen.getByText('Medication Regimens')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /\+ Add regimen/i })).toBeInTheDocument();
    });
  });

  it('shows empty state message when no active regimens', async () => {
    renderMedications();
    await waitFor(() =>
      expect(screen.getByText(/No active regimens/i)).toBeInTheDocument()
    );
  });
});

describe('Medications — form toggle', () => {
  beforeEach(() => {
    vi.mocked(client.fetchAllRegimens).mockResolvedValue(emptyRegimens);
    vi.mocked(client.fetchMedicationDefinitions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('shows form when + Add regimen is clicked', async () => {
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByRole('button', { name: /\+ Add regimen/i }));
    await user.click(screen.getByRole('button', { name: /\+ Add regimen/i }));
    expect(screen.getByText('New regimen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('hides form when Cancel is clicked', async () => {
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByRole('button', { name: /\+ Add regimen/i }));
    await user.click(screen.getByRole('button', { name: /\+ Add regimen/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.queryByText('New regimen')).not.toBeInTheDocument();
  });
});

describe('Medications — active regimen card', () => {
  beforeEach(() => {
    vi.mocked(client.fetchAllRegimens).mockResolvedValue({
      ...emptyRegimens,
      items: [activeRegimen],
      total: 1,
    });
    vi.mocked(client.fetchMedicationDefinitions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('renders medication name, dosage and frequency', async () => {
    renderMedications();
    await waitFor(() => {
      expect(screen.getByText('Omeprazole 20mg')).toBeInTheDocument();
      expect(screen.getByText(/20 mg/)).toBeInTheDocument();
      expect(screen.getByText(/Daily/i)).toBeInTheDocument();
    });
  });

  it('shows Stop button for active regimen', async () => {
    renderMedications();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^stop$/i })).toBeInTheDocument()
    );
  });

  it('calls deactivateRegimen when Stop is clicked', async () => {
    vi.mocked(client.deactivateRegimen).mockResolvedValue({ id: 'reg-1' });
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByRole('button', { name: /^stop$/i }));
    await user.click(screen.getByRole('button', { name: /^stop$/i }));
    expect(client.deactivateRegimen).toHaveBeenCalledWith('reg-1', USER_ID);
  });

  it('shows Log button on active regimen', async () => {
    renderMedications();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^log$/i })).toBeInTheDocument()
    );
  });

  it('calls createMedicationLog when Log is clicked', async () => {
    vi.mocked(client.createMedicationLog).mockResolvedValue({ id: 'log-1' });
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByRole('button', { name: /^log$/i }));
    await user.click(screen.getByRole('button', { name: /^log$/i }));
    expect(client.createMedicationLog).toHaveBeenCalledWith(
      expect.objectContaining({ regimen_id: 'reg-1', status: 'taken', user_id: USER_ID })
    );
  });

  it('shows ✓ Logged feedback after successful log', async () => {
    vi.mocked(client.createMedicationLog).mockResolvedValue({ id: 'log-1' });
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByRole('button', { name: /^log$/i }));
    await user.click(screen.getByRole('button', { name: /^log$/i }));
    await waitFor(() => expect(screen.getByText('✓ Logged')).toBeInTheDocument());
  });
});

describe('Medications — past regimens toggle', () => {
  beforeEach(() => {
    vi.mocked(client.fetchAllRegimens).mockResolvedValue({
      ...emptyRegimens,
      items: [activeRegimen, pastRegimen],
      total: 2,
    });
    vi.mocked(client.fetchMedicationDefinitions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('hides past regimen card by default', async () => {
    renderMedications();
    await waitFor(() => screen.getByText('Omeprazole 20mg'));
    expect(screen.queryByText('Ibuprofen 400mg')).not.toBeInTheDocument();
  });

  it('shows past regimen count in toggle button', async () => {
    renderMedications();
    await waitFor(() =>
      expect(screen.getByText(/1 past regimen/)).toBeInTheDocument()
    );
  });

  it('reveals past regimen on toggle click', async () => {
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByText(/1 past regimen/));
    await user.click(screen.getByText(/1 past regimen/));
    expect(screen.getByText('Ibuprofen 400mg')).toBeInTheDocument();
  });

  it('past regimen card has no Stop button', async () => {
    const user = userEvent.setup();
    renderMedications();
    await waitFor(() => screen.getByText(/1 past regimen/));
    await user.click(screen.getByText(/1 past regimen/));
    expect(screen.getAllByRole('button', { name: /^stop$/i })).toHaveLength(1);
  });
});
