/**
 * Garmin sync flow — covers the full POST /integrations/garmin/sync UI
 * contract from the Trust card's "Refresh Garmin" button:
 *
 *   · completed   → green "synced" note + today-v2 Garmin caches invalidated
 *   · no_new_data → neutral "no new data" note + caches still invalidated
 *                   (the run really executed, we just got no delta)
 *   · already_running → amber "already running" note, NO cache invalidation
 *                       (nothing new to render; existing data is still correct)
 *   · failed      → red "failed: …" note, NO cache invalidation
 *   · pending     → button disabled + text "Refreshing…"; a second click
 *                   while pending must NOT spawn a second syncGarmin call
 *   · ordering    → cache invalidation runs strictly AFTER syncGarmin resolves,
 *                   never before (so a failing sync doesn't silently blow the
 *                   cache and make the UI refetch for nothing)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Today from '../pages/Today';
import * as client from '../api/client';
import type {
  DailyCheckpointList,
  GarminSyncResponse,
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
    fetchMedicationAdherence: vi.fn(),
    fetchMeasurements: vi.fn(),
    fetchCheckpoints: vi.fn(),
    fetchSymptomLogs: vi.fn(),
    fetchLatestScaleReading: vi.fn(),
    fetchActiveRegimens: vi.fn(),
    fetchSystemStatus: vi.fn(),
    scanScale: vi.fn(),
    syncGarmin: vi.fn(),
  };
});

// ── Fixtures ───────────────────────────────────────────────────────────────

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
const neverMeasuredScale: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
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

const completedResponse: GarminSyncResponse = {
  status: 'completed',
  run_id: '019d9334-1111-7777-8888-000000000001',
  started_at: NOW,
  finished_at: NOW,
  error_message: null,
};

const noNewDataResponse: GarminSyncResponse = {
  status: 'no_new_data',
  run_id: '019d9334-1111-7777-8888-000000000002',
  started_at: NOW,
  finished_at: NOW,
  error_message: null,
};

const alreadyRunningResponse: GarminSyncResponse = {
  status: 'already_running',
  run_id: null,
  started_at: null,
  finished_at: null,
  error_message: null,
};

const failedResponse: GarminSyncResponse = {
  status: 'failed',
  run_id: '019d9334-1111-7777-8888-000000000003',
  started_at: NOW,
  finished_at: NOW,
  error_message: 'sync_garmin.py exited rc=1',
};

// ── Render helpers ─────────────────────────────────────────────────────────

function renderToday() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Today onOpenCapture={vi.fn()} onGoToSettings={vi.fn()} />
    </QueryClientProvider>,
  );
  return qc;
}

async function clickRefreshAndWait() {
  await waitFor(() => expect(screen.getByTestId('today-trust')).toBeInTheDocument());
  const btn = screen.getByRole('button', { name: /refresh garmin/i });
  fireEvent.click(btn);
  return btn;
}

// ── Setup ──────────────────────────────────────────────────────────────────

describe('Garmin sync UI flow', () => {
  beforeEach(() => {
    vi.mocked(client.fetchMedicationAdherence).mockResolvedValue(emptyAdherence);
    vi.mocked(client.fetchMeasurements).mockResolvedValue(emptyMeasurements);
    vi.mocked(client.fetchCheckpoints).mockResolvedValue(emptyCheckpoints);
    vi.mocked(client.fetchSymptomLogs).mockResolvedValue(emptySymptoms);
    vi.mocked(client.fetchLatestScaleReading).mockResolvedValue(neverMeasuredScale);
    vi.mocked(client.fetchActiveRegimens).mockResolvedValue(emptyRegimens);
    vi.mocked(client.fetchSystemStatus).mockResolvedValue(defaultSystemStatus);
  });

  afterEach(() => vi.clearAllMocks());

  it('completed → shows "synced" note and invalidates Garmin caches', async () => {
    vi.mocked(client.syncGarmin).mockResolvedValue(completedResponse);
    const qc = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await clickRefreshAndWait();

    await waitFor(() => expect(vi.mocked(client.syncGarmin)).toHaveBeenCalledWith('test-user-id'));

    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/synced/);
    expect(note.getAttribute('data-status')).toBe('completed');

    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
    expect(keys.some((k) => k.includes('today-v2') && k.includes('hrv_rmssd'))).toBe(true);
    expect(keys.some((k) => k.includes('today-v2') && k.includes('resting_hr'))).toBe(true);
    expect(keys.some((k) => k.includes('today-v2') && k.includes('system-status'))).toBe(true);
    expect(keys.some((k) => k.includes('freshness-garmin'))).toBe(true);
  });

  it('no_new_data → shows "no new data" note and still invalidates (run did execute)', async () => {
    vi.mocked(client.syncGarmin).mockResolvedValue(noNewDataResponse);
    const qc = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await clickRefreshAndWait();

    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/no new data/);
    expect(note.getAttribute('data-status')).toBe('no_new_data');

    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
    expect(keys.some((k) => k.includes('today-v2') && k.includes('hrv_rmssd'))).toBe(true);
  });

  it('already_running → shows "already running" note and does NOT invalidate', async () => {
    vi.mocked(client.syncGarmin).mockResolvedValue(alreadyRunningResponse);
    const qc = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await clickRefreshAndWait();

    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/already running/);
    expect(note.getAttribute('data-status')).toBe('already_running');

    // Give any pending invalidation microtasks a chance to flush, then assert
    // none of them targeted a Garmin-related cache.
    await act(async () => {
      await Promise.resolve();
    });
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
    expect(keys.some((k) => k.includes('today-v2') && k.includes('hrv_rmssd'))).toBe(false);
    expect(keys.some((k) => k.includes('freshness-garmin'))).toBe(false);
  });

  it('failed → shows red "failed: …" note and does NOT invalidate', async () => {
    vi.mocked(client.syncGarmin).mockResolvedValue(failedResponse);
    const qc = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await clickRefreshAndWait();

    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/failed:.*rc=1/);
    expect(note.getAttribute('data-status')).toBe('failed');

    await act(async () => {
      await Promise.resolve();
    });
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
    expect(keys.some((k) => k.includes('today-v2') && k.includes('hrv_rmssd'))).toBe(false);
    expect(keys.some((k) => k.includes('freshness-garmin'))).toBe(false);
  });

  it('network failure → shows "failed: <error>" note and does NOT invalidate', async () => {
    vi.mocked(client.syncGarmin).mockRejectedValue(new Error('500: boom'));
    const qc = renderToday();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await clickRefreshAndWait();

    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/failed:.*500: boom/);
    expect(note.getAttribute('data-status')).toBe('failed');

    await act(async () => {
      await Promise.resolve();
    });
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey ?? []));
    expect(keys.some((k) => k.includes('freshness-garmin'))).toBe(false);
  });

  it('pending state → button disabled + text "Refreshing…"; double-click triggers only one call', async () => {
    // Hold the syncGarmin call pending until we release it manually.
    let release: ((v: GarminSyncResponse) => void) | null = null;
    const pending = new Promise<GarminSyncResponse>((resolve) => {
      release = resolve;
    });
    vi.mocked(client.syncGarmin).mockReturnValue(pending);

    renderToday();
    const btn = await clickRefreshAndWait();

    // While in flight: button shows Refreshing… and is disabled.
    await waitFor(() => expect(btn.textContent).toMatch(/Refreshing…/));
    expect((btn as HTMLButtonElement).disabled).toBe(true);

    // Try to double-click — disabled button must not fire a second call.
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(vi.mocked(client.syncGarmin)).toHaveBeenCalledTimes(1);

    // Release the pending promise and verify the note flips to synced.
    release!(completedResponse);
    const note = await screen.findByTestId('garmin-sync-note');
    expect(note.textContent).toMatch(/synced/);
    await waitFor(() => expect((btn as HTMLButtonElement).disabled).toBe(false));
  });

  it('invalidation runs strictly AFTER syncGarmin resolves, never before', async () => {
    const order: string[] = [];
    vi.mocked(client.syncGarmin).mockImplementation(async () => {
      order.push('sync-start');
      await new Promise((r) => setTimeout(r, 10));
      order.push('sync-resolve');
      return completedResponse;
    });
    const qc = renderToday();
    vi.spyOn(qc, 'invalidateQueries').mockImplementation(async (filter) => {
      const key = JSON.stringify(filter?.queryKey ?? []);
      if (key.includes('today-v2') && key.includes('hrv_rmssd')) {
        order.push('invalidate-hrv');
      }
      return undefined;
    });

    await clickRefreshAndWait();

    await waitFor(() => expect(order).toContain('invalidate-hrv'));
    const syncIdx = order.indexOf('sync-resolve');
    const invIdx = order.indexOf('invalidate-hrv');
    expect(syncIdx).toBeGreaterThanOrEqual(0);
    expect(invIdx).toBeGreaterThan(syncIdx);
  });
});
