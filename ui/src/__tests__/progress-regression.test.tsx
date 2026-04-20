/**
 * B5C — Progress regression tests
 *
 * Five scenarios not covered by progress-ui.test.tsx:
 *  1. overallState = 'mixed' chip renders "Mixed coverage"
 *  2. Clicking the Progress nav tab renders the Progress page (App shell integration)
 *  3. fetchCheckpoints rejects → all 5 blocks still render, consistency shows "insufficient"
 *  4. fetchSystemStatus rejects → page renders, freshness shows both sources degraded
 *  5. fetchSummary rejects → page renders, analytical coverage shows zero blocks
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import Progress from '../pages/Progress';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  DailyCheckpointResponse,
  InsightSummary,
  LatestScaleReading,
  MeasurementList,
  MedicationAdherenceResponse,
  MedicationRegimenList,
  SymptomLogList,
  SystemStatusResponse,
} from '../api/types';

// ── Time anchor ───────────────────────────────────────────────────────────
const DATE = '2026-04-18';
const NOW = '2026-04-18T14:00:00.000Z';

vi.mock('../config', () => ({
  getUserId: () => 'test-user-id',
  setUserId: vi.fn(),
}));

vi.mock('../lib/scaleProfile', () => ({
  loadScaleProfile: () => ({}),
  saveScaleProfile: vi.fn(),
}));

vi.mock('../lib/scaleDevice', () => ({
  loadScaleDevice: () => null,
  saveScaleDevice: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    todayISO: () => DATE,
    nowISO: () => NOW,
    // Shared by Progress + Today
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchMedicationAdherence: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchSystemStatus: vi.fn(),
    // Progress-only
    fetchSummary: vi.fn(),
    // Today-only
    fetchLatestScaleReading: vi.fn(),
    fetchActiveRegimens: vi.fn(),
  };
});

// ── Fixtures ──────────────────────────────────────────────────────────────

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

const emptyCheckpoints: DailyCheckpointList = { items: [], total: 0, offset: 0, limit: 14 };
const emptyMeasurements: MeasurementList = { items: [], total: 0, offset: 0, limit: 14 };
const emptySymptoms: SymptomLogList = { items: [], total: 0, offset: 0, limit: 50 };
const emptyRegimens: MedicationRegimenList = { items: [], total: 0, offset: 0, limit: 1 };
const emptyAdherence: MedicationAdherenceResponse = {
  user_id: 'test-user-id',
  items: [],
  overall_adherence_pct: null,
  availability_status: 'not_applicable',
};
const neverMeasuredScale: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};

function makeSystemStatus(): SystemStatusResponse {
  return {
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
}

function makeSummary(): InsightSummary {
  return {
    user_id: 'test-user-id',
    as_of: NOW,
    overall_adherence_pct: null,
    active_deviations: 0,
    current_symptom_burden: 0,
    illness_signal: 'none',
    recovery_status: 'normal',
    block_availability: {
      deviations: 'ok',
      illness: 'ok',
      recovery: 'ok',
      adherence: 'ok',
      symptoms: 'ok',
    },
    data_availability: null,
  };
}

// ── Render helpers ─────────────────────────────────────────────────────────

function renderProgressStandalone() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Progress />
    </QueryClientProvider>,
  );
}

// ── Seed helpers ───────────────────────────────────────────────────────────

function seedProgressDefaults() {
  vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
  vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms);
  vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(emptyAdherence);
  vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
  vi.mocked(client.fetchSummary).mockResolvedValue(makeSummary());
  vi.mocked(client.fetchSystemStatus).mockResolvedValue(makeSystemStatus());
}

function seedTodayDefaults() {
  vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  vi.mocked(client.fetchActiveRegimens).mockResolvedValue(emptyRegimens);
}

beforeEach(() => {
  seedProgressDefaults();
  seedTodayDefaults();
});

afterEach(() => vi.clearAllMocks());

// ── Tests ──────────────────────────────────────────────────────────────────

describe('Progress regression', () => {
  // 1. overallState scoring: consistency sufficient (score 2) + signal insufficient (score 0)
  //    → total 2 / max 4 → 'mixed'
  it('renders "Mixed coverage" chip when consistency is sufficient but signal is insufficient', async () => {
    // 10 checkpoints → checkInRate = 10/14 ≈ 71% ≥ CONSISTENCY_SUFFICIENT_THRESHOLD → sufficient
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(makeCheckpoints(10));
    // No measurements → both hrv + rhr null → signal insufficient

    renderProgressStandalone();

    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());
    const chip = screen.getByTestId('progress-overall-state');
    expect(chip.getAttribute('data-state')).toBe('mixed');
    expect(chip.textContent).toMatch(/mixed coverage/i);
  });

  // 2. Full app shell: clicking the Progress nav button renders the Progress page
  it('clicking the Progress nav tab renders the Progress page', async () => {
    render(<App />);

    // Wait for Today to stabilise
    await waitFor(() => expect(screen.getByTestId('today-trust')).toBeInTheDocument());

    // Navigate to Progress
    fireEvent.click(screen.getByRole('button', { name: /^progress$/i }));

    // Progress hero must appear; Today panel must be gone
    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());
    expect(screen.queryByTestId('today-trust')).toBeNull();
  });

  // 3. Partial failure: fetchCheckpoints rejects — page degrades to 'limited' state
  //    systemStatus + summary resolve → hasAnySources=true; scores=0 → limited
  //    limited renders: HeroCard + DataConfidenceCard + ProgressEmptyState (no analytical cards)
  it('fetchCheckpoints rejects → page degrades to limited state, analytical cards hidden', async () => {
    vi.mocked(client.fetchCheckpoints).mockRejectedValue(new Error('network'));

    renderProgressStandalone();

    await waitFor(() => expect(screen.getByTestId('progress-hero')).toBeInTheDocument());

    // limited state: DataConfidenceCard and empty state shown
    expect(screen.getByTestId('progress-confidence')).toBeInTheDocument();
    expect(screen.getByTestId('progress-empty')).toBeInTheDocument();

    // analytical cards are hidden in limited state
    expect(screen.queryByTestId('progress-consistency')).toBeNull();
    expect(screen.queryByTestId('progress-signal')).toBeNull();
  });

  // 4. systemStatus null: fetchSystemStatus rejects → both sources shown as degraded
  it('page renders without crash when fetchSystemStatus rejects', async () => {
    vi.mocked(client.fetchSystemStatus).mockRejectedValue(new Error('network'));

    renderProgressStandalone();

    await waitFor(() => expect(screen.getByTestId('progress-confidence')).toBeInTheDocument());

    const freshness = screen.getByTestId('progress-confidence-freshness');
    // systemStatus = null → garminSource undefined → garminOk = false
    expect(freshness.textContent).toMatch(/not configured or error/i);
    // systemStatus = null → scaleSource undefined → scaleOk = false
    expect(freshness.textContent).toMatch(/not paired/i);
  });

  // 5. summary null: fetchSummary rejects → totalBlocks = 0, analytical section shows no "N/M with data"
  //    systemStatus resolves → hasAnySources=true; scores=0 → limited state
  //    limited renders: HeroCard + DataConfidenceCard + ProgressEmptyState (no analytical cards)
  it('fetchSummary rejects → page renders, analytical coverage shows zero blocks, analytical cards hidden', async () => {
    vi.mocked(client.fetchSummary).mockRejectedValue(new Error('network'));

    renderProgressStandalone();

    await waitFor(() => expect(screen.getByTestId('progress-confidence')).toBeInTheDocument());

    // summary = null → blockStatuses = [] → totalBlocks = 0 → "Analysis blocks" row absent
    const analytical = screen.getByTestId('progress-confidence-analytical');
    expect(analytical.textContent).not.toMatch(/analysis blocks/i);

    // Page fully renders — no crash
    expect(screen.getByTestId('progress-hero')).toBeInTheDocument();
    expect(screen.getByTestId('progress-empty')).toBeInTheDocument();

    // analytical cards hidden in limited state
    expect(screen.queryByTestId('progress-consistency')).toBeNull();
  });
});
