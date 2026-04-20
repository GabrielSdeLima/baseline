import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Today from '../pages/Today';
import * as client from '../api/client';
import type {
  DailyCheckpointResponse,
  LatestScaleReading,
  MeasurementList,
  MedicationAdherenceResponse,
  MedicationRegimenList,
  SymptomLogList,
  SystemStatusResponse,
  DailyCheckpointList,
} from '../api/types';

// ── Fixed time anchors so derivation is deterministic ─────────────────────

const DATE = '2026-04-17';
const NOW = '2026-04-17T18:00:00.000Z';

vi.mock('../config', () => ({
  getUserId: () => 'test-user',
  setUserId: vi.fn(),
}));

vi.mock('../lib/scaleProfile', () => ({
  loadScaleProfile: () => ({}),
}));
vi.mock('../lib/scaleDevice', () => ({
  loadScaleDevice: () => null,
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    todayISO: () => DATE,
    nowISO: () => NOW,
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    fetchMedicationAdherence: vi.fn(),
    fetchActiveRegimens: vi.fn(),
    fetchSystemStatus: vi.fn(),
    scanScale: vi.fn(),
    syncGarmin: vi.fn(),
  };
});

// ── Fixture builders ──────────────────────────────────────────────────────

function measurementList(items: MeasurementList['items']): MeasurementList {
  return { items, total: items.length, offset: 0, limit: items.length || 1 };
}

function checkpointList(items: DailyCheckpointResponse[]): DailyCheckpointList {
  return { items, total: items.length, offset: 0, limit: items.length || 14 };
}

function symptomList(items: SymptomLogList['items']): SymptomLogList {
  return { items, total: items.length, offset: 0, limit: 50 };
}

function regimenList(items: MedicationRegimenList['items']): MedicationRegimenList {
  return { items, total: items.length, offset: 0, limit: items.length || 1 };
}

const neverMeasuredScale: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};

const defaultSystemStatus: SystemStatusResponse = {
  user_id: 'test-user',
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
  agents: [
    {
      agent_type: 'garmin_sync',
      display_name: 'Garmin sync',
      status: 'active',
      last_seen_at: NOW,
    },
  ],
  as_of: NOW,
};

const defaultAdherence: MedicationAdherenceResponse = {
  user_id: 'test-user',
  items: [],
  overall_adherence_pct: null,
  availability_status: 'not_applicable',
};

function hrv(measuredAt: string, value = 55) {
  return {
    id: `m-hrv-${measuredAt}`,
    user_id: 'test-user',
    metric_type_slug: 'hrv_rmssd',
    metric_type_name: 'HRV RMSSD',
    source_slug: 'garmin_connect',
    value_num: value,
    unit: 'ms',
    measured_at: measuredAt,
    aggregation_level: 'raw',
  };
}

function weight(measuredAt: string, value = 75.2) {
  return {
    id: `m-weight-${measuredAt}`,
    user_id: 'test-user',
    metric_type_slug: 'weight',
    metric_type_name: 'Weight',
    source_slug: 'hc900_ble',
    value_num: value,
    unit: 'kg',
    measured_at: measuredAt,
    aggregation_level: 'raw',
  };
}

function checkpoint(type: 'morning' | 'night'): DailyCheckpointResponse {
  return {
    id: `cp-${type}`,
    user_id: 'test-user',
    checkpoint_type: type,
    checkpoint_date: DATE,
    checkpoint_at: `${DATE}T${type === 'morning' ? '08' : '22'}:00:00.000Z`,
    mood: 7,
    energy: 7,
    sleep_quality: type === 'morning' ? 7 : null,
    body_state_score: null,
    notes: null,
  };
}

// ── Default setup: empty day, scale paired, nothing logged ────────────────

function setupDefaults() {
  vi.mocked(client.fetchCheckpoints).mockResolvedValue(checkpointList([]));
  vi.mocked(client.fetchSymptomLogs).mockResolvedValue(symptomList([]));
  vi.mocked(client.fetchMeasurements).mockResolvedValue(measurementList([]));
  vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
  vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(defaultAdherence);
  vi.mocked(client.fetchActiveRegimens).mockResolvedValue(regimenList([]));
  vi.mocked(client.fetchSystemStatus).mockResolvedValue(defaultSystemStatus);
  vi.mocked(client.scanScale).mockResolvedValue({ status: 'ok', message: 'Weight captured' });
}

function renderToday(onOpenCapture = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Today onOpenCapture={onOpenCapture} onGoToSettings={vi.fn()} />
    </QueryClientProvider>,
  );
  return { qc, onOpenCapture };
}

// ── Tests ─────────────────────────────────────────────────────────────────

describe('Today v2 Home — loading + error', () => {
  beforeEach(() => {
    vi.mocked(client.fetchCheckpoints).mockReset();
    vi.mocked(client.fetchMeasurements).mockReset();
    vi.mocked(client.fetchSymptomLogs).mockReset();
    vi.mocked(client.fetchLatestScaleReading).mockReset();
    vi.mocked(client.fetchMedicationAdherence).mockReset();
    vi.mocked(client.fetchActiveRegimens).mockReset();
    vi.mocked(client.fetchSystemStatus).mockReset();
  });
  afterEach(() => vi.clearAllMocks());

  // 1. loading
  it('renders loading skeleton while sources are fetching', async () => {
    // Never-resolving promises keep queries in loading state.
    const pending = new Promise<never>(() => {});
    vi.mocked(client.fetchCheckpoints).mockReturnValue(pending as unknown as Promise<DailyCheckpointList>);
    vi.mocked(client.fetchSymptomLogs).mockReturnValue(pending as unknown as Promise<SymptomLogList>);
    vi.mocked(client.fetchMeasurements).mockReturnValue(pending as unknown as Promise<MeasurementList>);
    vi.mocked(client.fetchLatestScaleReading).mockReturnValue(pending as unknown as Promise<LatestScaleReading>);
    vi.mocked(client.fetchMedicationAdherence).mockReturnValue(pending as unknown as Promise<MedicationAdherenceResponse>);
    vi.mocked(client.fetchActiveRegimens).mockReturnValue(pending as unknown as Promise<MedicationRegimenList>);
    vi.mocked(client.fetchSystemStatus).mockReturnValue(pending as unknown as Promise<SystemStatusResponse>);

    renderToday();
    expect(screen.getByTestId('today-loading')).toBeInTheDocument();
  });

  // 2a. partial error — page still renders, inline banner explains what failed
  it('renders a partial-error banner when a single source rejects (page still renders)', async () => {
    setupDefaults();
    vi.mocked(client.fetchSystemStatus).mockRejectedValue(new Error('status 500: boom'));

    renderToday();
    await waitFor(() =>
      expect(screen.getByTestId('today-partial-error')).toBeInTheDocument(),
    );
    // Banner labels which source failed and surfaces the error message.
    const banner = screen.getByTestId('today-partial-error');
    expect(banner.textContent).toMatch(/system-status/i);
    expect(banner.textContent).toMatch(/boom/);
    // Hero still renders — the rest of the page is not blocked by one failure.
    expect(screen.getByTestId('today-hero')).toBeInTheDocument();
    expect(screen.queryByTestId('today-error')).not.toBeInTheDocument();
  });

  // 2b. fully errored — every source failed, page cannot derive anything
  it('renders the full error block only when every source query rejects', async () => {
    const boom = new Error('network down');
    vi.mocked(client.fetchCheckpoints).mockRejectedValue(boom);
    vi.mocked(client.fetchSymptomLogs).mockRejectedValue(boom);
    vi.mocked(client.fetchMeasurements).mockRejectedValue(boom);
    vi.mocked(client.fetchLatestScaleReading).mockRejectedValue(boom);
    vi.mocked(client.fetchMedicationAdherence).mockRejectedValue(boom);
    vi.mocked(client.fetchActiveRegimens).mockRejectedValue(boom);
    vi.mocked(client.fetchSystemStatus).mockRejectedValue(boom);

    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-error')).toBeInTheDocument());
    expect(screen.getByTestId('today-error').textContent).toMatch(/network down/);
    // Hero should NOT render when nothing could be derived.
    expect(screen.queryByTestId('today-hero')).not.toBeInTheDocument();
  });
});

describe('Today v2 Home — hero variants', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  // 3. state=ok → confirmation hero
  it('state=ok renders a confirmation hero ("Day on track")', async () => {
    // No required items missing: disable all required items that need real logs
    // by flipping the protocol via complete day fixtures.
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      checkpointList([checkpoint('morning'), checkpoint('night')]),
    );
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'weight') return Promise.resolve(measurementList([weight(`${DATE}T07:00:00.000Z`)]));
      if (slug === 'hrv_rmssd')
        return Promise.resolve(measurementList([hrv(`${DATE}T06:00:00.000Z`)]));
      if (slug === 'resting_hr') return Promise.resolve(measurementList([]));
      if (slug === 'body_temperature') return Promise.resolve(measurementList([]));
      return Promise.resolve(measurementList([]));
    });
    // No active regimens ⇒ medication not_applicable.
    vi.mocked(client.fetchActiveRegimens).mockResolvedValue(regimenList([]));

    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-hero')).toBeInTheDocument());
    expect(screen.getByText('Day on track')).toBeInTheDocument();
    expect(screen.getByTestId('today-hero').textContent?.toLowerCase()).toContain('ok');
  });

  // 4. state=action_needed → hero shows action button; click maps to correct tab
  it('state=action_needed renders a next-action button that opens the matching modal tab', async () => {
    // Default fixtures → empty day, morning not logged yet, no blockers:
    // top action is morning check-in ⇒ maps to 'checkpoint' tab.
    const { onOpenCapture } = renderToday();

    await waitFor(() => expect(screen.getByTestId('today-hero')).toBeInTheDocument());
    expect(screen.getByTestId('today-hero').textContent?.toLowerCase()).toContain('action');

    const heroButton = screen.getByRole('button', { name: /morning check-in/i });
    fireEvent.click(heroButton);
    expect(onOpenCapture).toHaveBeenCalledWith('checkpoint');
  });

  // 5. state=blocked → hero shows blocker message + resolution hint
  it('state=blocked renders a blocker hero with message and resolution hint', async () => {
    // Scale unpaired + weight is the only required item missing ⇒ only weight is
    // required-incomplete and it is blocked, so state=blocked.
    // Accomplish via protocol-by-default: simulate by leaving everything else
    // complete or not_applicable through source fixtures.
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(
      checkpointList([checkpoint('morning'), checkpoint('night')]),
    );
    vi.mocked(client.fetchMeasurements).mockImplementation((_u, slug) => {
      if (slug === 'hrv_rmssd')
        return Promise.resolve(measurementList([hrv(`${DATE}T06:00:00.000Z`)]));
      return Promise.resolve(measurementList([]));
    });
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...defaultSystemStatus,
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
          device_paired: false,
          last_sync_at: NOW,
          last_advanced_at: NOW,
          last_run_status: 'ok',
          last_run_at: NOW,
        },
      ],
    });

    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-hero')).toBeInTheDocument());
    const hero = screen.getByTestId('today-hero');
    expect(hero.textContent?.toLowerCase()).toContain('blocked');
    // Hero carries both the blocker message (headline) and the resolution hint.
    expect(hero.textContent).toMatch(/HC900 scale not paired/i);
    expect(hero.textContent).toMatch(/Pair a scale in Settings/i);
  });
});

describe('Today v2 Home — zones', () => {
  beforeEach(setupDefaults);
  afterEach(() => vi.clearAllMocks());

  // 6. Actions list renders in priority order with #1 first
  it('renders the actions list with ranked items in priority order', async () => {
    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-actions')).toBeInTheDocument());

    const actionsSection = screen.getByTestId('today-actions');
    const items = actionsSection.querySelectorAll('li');
    expect(items.length).toBeGreaterThan(1);
    // Top-ranked action is check-in (day_integrity beats improves_trust).
    expect(items[0].textContent).toContain('Morning check-in');
    expect(items[0].textContent).toContain('#1');
  });

  // 7. Completion card shows all required + logs required/done summary
  it('renders the completion card with required counts and per-kind detail', async () => {
    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-completion')).toBeInTheDocument());

    const completion = screen.getByTestId('today-completion');
    expect(completion.textContent).toContain('Check-in');
    expect(completion.textContent).toContain('Check-out');
    expect(completion.textContent).toContain('Weight');
    expect(completion.textContent).toContain('Garmin');
    expect(completion.textContent).toMatch(/\d+\/\d+ required/);
  });

  // 8. Blockers card appears when weight is blocked
  it('renders the blockers card only when there are blockers', async () => {
    vi.mocked(client.fetchSystemStatus).mockResolvedValue({
      ...defaultSystemStatus,
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
          device_paired: false,
          last_sync_at: NOW,
          last_advanced_at: NOW,
          last_run_status: 'ok',
          last_run_at: NOW,
        },
      ],
    });

    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-blockers')).toBeInTheDocument());
    const blockers = screen.getByTestId('today-blockers');
    expect(blockers.textContent).toContain('HC900 scale not paired');
    expect(blockers.textContent).toContain('device_not_paired');
  });

  // 9. Blockers card absent when no blockers
  it('does not render the blockers card when there are no blockers', async () => {
    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-hero')).toBeInTheDocument());
    expect(screen.queryByTestId('today-blockers')).not.toBeInTheDocument();
  });

  // 10. Trust card + Refresh Garmin calls the real sync endpoint and then invalidates
  it('Refresh Garmin button triggers the sync endpoint before invalidating caches', async () => {
    vi.mocked(client.syncGarmin).mockResolvedValue({
      status: 'completed',
      run_id: '019d9334-1111-7777-8888-000000000001',
      started_at: NOW,
      finished_at: NOW,
      error_message: null,
    });
    const { qc } = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await waitFor(() => expect(screen.getByTestId('today-trust')).toBeInTheDocument());
    const refreshBtn = screen.getByRole('button', { name: /refresh garmin/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => expect(vi.mocked(client.syncGarmin)).toHaveBeenCalledTimes(1));

    await waitFor(() => {
      const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
      expect(keys.some((k) => k.includes('today-v2') && k.includes('hrv_rmssd'))).toBe(true);
      expect(keys.some((k) => k.includes('today-v2') && k.includes('resting_hr'))).toBe(true);
      expect(keys.some((k) => k.includes('today-v2') && k.includes('system-status'))).toBe(true);
    });
  });

  // 11. Weight action triggers scanScale (real action, not a modal)
  it('clicking the weight action triggers a scale scan', async () => {
    renderToday();
    await waitFor(() => expect(screen.getByTestId('today-actions')).toBeInTheDocument());

    // Weight appears in the ranked list once check-in/check-out are visible;
    // locate its "Do" button by climbing from the label.
    const weighLabel = screen.getByText(/^Weigh in$/);
    const weighItem = weighLabel.closest('li');
    expect(weighItem).not.toBeNull();
    const doBtn = weighItem!.querySelector('button');
    expect(doBtn).not.toBeNull();
    fireEvent.click(doBtn!);

    await waitFor(() => expect(vi.mocked(client.scanScale)).toHaveBeenCalledTimes(1));
  });
});
