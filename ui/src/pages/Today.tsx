import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getUserId } from '../config';
import { scanScale, syncGarmin, createMedicationLog, nowISO } from '../api/client';
import type { GarminSyncResponse, GarminSyncStatus, MedicationRegimenList } from '../api/types';
import { loadScaleProfile } from '../lib/scaleProfile';
import { loadScaleDevice } from '../lib/scaleDevice';
import type { CaptureSection } from '../components/CaptureSurface';
import { useTodayViewModel } from '../features/today/useTodayViewModel';
import TodayHeroCard from '../features/today/components/TodayHeroCard';
import TodayActionsList from '../features/today/components/TodayActionsList';
import TodayCompletionCard from '../features/today/components/TodayCompletionCard';
import TodayBlockersCard from '../features/today/components/TodayBlockersCard';
import TodayTrustCard from '../features/today/components/TodayTrustCard';
import type { ProtocolKind } from '../features/today/types';

const SCAN_TIMEOUT_S = 45;

const KIND_TO_SECTION: Partial<Record<ProtocolKind, CaptureSection>> = {
  check_in: 'checkpoint',
  check_out: 'checkpoint',
  symptoms: 'symptom',
  temperature: 'measurement',
};

function noteForGarminStatus(r: GarminSyncResponse): string {
  switch (r.status) {
    case 'completed':
      return 'synced';
    case 'no_new_data':
      return 'no new data';
    case 'already_running':
      return 'already running';
    case 'failed':
      return `failed: ${r.error_message ?? 'unknown error'}`;
  }
}

interface Props {
  onOpenCapture: (section?: CaptureSection) => void;
  onGoToSettings: () => void;
}

export default function Today({ onOpenCapture, onGoToSettings }: Props) {
  const userId = getUserId();
  const qc = useQueryClient();
  const { vm, isLoading, isFullyErrored, queryErrors } = useTodayViewModel({ userId });

  const [pendingActionId, setPendingActionId] = useState<string | undefined>(undefined);
  const [scanMsg, setScanMsg] = useState('');
  const [scanCountdown, setScanCountdown] = useState<number | null>(null);
  const [garminSyncOutcome, setGarminSyncOutcome] = useState<
    { status: GarminSyncStatus; note: string } | null
  >(null);
  const [medConfirmNote, setMedConfirmNote] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scaleMut = useMutation({
    mutationFn: () => {
      abortRef.current = new AbortController();
      return scanScale(
        userId,
        abortRef.current.signal,
        loadScaleProfile(),
        loadScaleDevice()?.mac,
      );
    },
    onSuccess: (data) => {
      setScanMsg(data.message);
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      qc.invalidateQueries({ queryKey: ['scale-latest'] });
      qc.invalidateQueries({ queryKey: ['measurements'] });
      qc.invalidateQueries({ queryKey: ['freshness-scale'] });
      setTimeout(() => setScanMsg(''), 5000);
    },
    onError: (e: Error) => {
      if (e.name !== 'AbortError') {
        setScanMsg(e.message);
        setTimeout(() => setScanMsg(''), 8000);
      }
    },
    onSettled: () => setPendingActionId(undefined),
  });

  const garminRefreshMut = useMutation({
    mutationFn: () => syncGarmin(userId),
    onSuccess: async (data: GarminSyncResponse) => {
      setGarminSyncOutcome({ status: data.status, note: noteForGarminStatus(data) });
      // Only re-fetch queries when the server actually touched data — a failed
      // or already_running response would otherwise burn a round-trip for no
      // change.  no_new_data still invalidates: the user asked for fresh data
      // and we want the UI to reflect today's run metadata even if Garmin had
      // nothing new to publish.
      if (data.status === 'completed' || data.status === 'no_new_data') {
        await Promise.all([
          qc.invalidateQueries({ queryKey: ['today-v2', 'measurements', userId, 'hrv_rmssd'] }),
          qc.invalidateQueries({ queryKey: ['today-v2', 'measurements', userId, 'resting_hr'] }),
          qc.invalidateQueries({ queryKey: ['today-v2', 'system-status', userId] }),
          qc.invalidateQueries({ queryKey: ['freshness-garmin', userId] }),
          qc.invalidateQueries({ queryKey: ['system-status', userId] }),
        ]);
      }
      setTimeout(() => setGarminSyncOutcome(null), 5000);
    },
    onError: (e: Error) => {
      setGarminSyncOutcome({ status: 'failed', note: `failed: ${e.message}` });
      setTimeout(() => setGarminSyncOutcome(null), 8000);
    },
    onSettled: () => setPendingActionId(undefined),
  });

  const confirmMedsMut = useMutation({
    mutationFn: async () => {
      const regimens =
        qc.getQueryData<MedicationRegimenList>(['today-v2', 'regimens', userId])?.items ?? [];
      if (regimens.length === 0) throw new Error('no active regimens in cache');
      const now = nowISO();
      await Promise.all(
        regimens.map((r) =>
          createMedicationLog({
            user_id: userId,
            regimen_id: r.id,
            status: 'taken',
            scheduled_at: now,
            taken_at: now,
            recorded_at: now,
          }),
        ),
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['today-v2', 'med-logs', userId] });
      setMedConfirmNote('logged');
      setTimeout(() => setMedConfirmNote(null), 5000);
    },
    onError: (e: Error) => {
      setMedConfirmNote(`failed: ${e.message}`);
      setTimeout(() => setMedConfirmNote(null), 8000);
    },
    onSettled: () => setPendingActionId(undefined),
  });

  useEffect(() => {
    if (!scaleMut.isPending) {
      setScanCountdown(null);
      return;
    }
    let remaining = SCAN_TIMEOUT_S;
    setScanCountdown(remaining);
    const id = setInterval(() => {
      remaining -= 1;
      setScanCountdown(remaining <= 0 ? 0 : remaining);
      if (remaining <= 0) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [scaleMut.isPending]);

  function handleExecuteAction(actionId: string) {
    const action = vm.priorityActions.find((a) => a.id === actionId);
    if (!action) return;

    if (action.kind === 'weight') {
      setPendingActionId(actionId);
      scaleMut.mutate();
      return;
    }
    if (action.kind === 'garmin') {
      setPendingActionId(actionId);
      garminRefreshMut.mutate();
      return;
    }
    if (action.kind === 'medication') {
      setPendingActionId(actionId);
      confirmMedsMut.mutate();
      return;
    }
    const section = KIND_TO_SECTION[action.kind];
    if (section) onOpenCapture(section);
  }

  function handleResolveBlocker(_blockerId: string) {
    onGoToSettings();
  }

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="today-loading">
        <div className="bg-white border border-gray-200 rounded-lg p-4 animate-pulse">
          <div className="h-3 bg-gray-100 rounded w-1/3 mb-3" />
          <div className="h-5 bg-gray-100 rounded w-2/3 mb-2" />
          <div className="h-3 bg-gray-100 rounded w-1/2" />
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 animate-pulse">
          <div className="h-3 bg-gray-100 rounded w-1/4 mb-2" />
          <div className="h-3 bg-gray-100 rounded w-full" />
        </div>
      </div>
    );
  }

  if (isFullyErrored) {
    return (
      <div
        data-testid="today-error"
        className="bg-white border border-red-200 rounded-lg p-4"
      >
        <p className="text-sm text-red-700 font-medium">Could not load today</p>
        <ul className="mt-2 text-xs text-gray-500 space-y-1 font-mono">
          {queryErrors.slice(0, 5).map((e) => (
            <li key={e.source}>
              · {e.source}: {e.error.message}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {queryErrors.length > 0 && (
        <div
          data-testid="today-partial-error"
          className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2"
        >
          <p className="text-xs text-amber-800">
            Some sources failed — rendering with what loaded.
          </p>
          <ul className="mt-1 text-[10px] text-amber-700 font-mono space-y-0.5">
            {queryErrors.slice(0, 5).map((e) => (
              <li key={e.source}>· {e.source}: {e.error.message}</li>
            ))}
          </ul>
        </div>
      )}

      <TodayHeroCard
        vm={vm}
        onExecuteAction={handleExecuteAction}
        onResolveBlocker={handleResolveBlocker}
        actionPending={pendingActionId}
      />

      <TodayActionsList
        actions={vm.priorityActions}
        onExecuteAction={handleExecuteAction}
        actionPending={pendingActionId}
      />

      {(scanMsg || scanCountdown !== null) && (
        <div className="text-[11px] text-gray-500 font-mono bg-gray-50 border border-gray-100 rounded px-3 py-1.5">
          {scaleMut.isPending
            ? `Scale scanning… ${scanCountdown ?? SCAN_TIMEOUT_S}s`
            : scanMsg}
        </div>
      )}

      {medConfirmNote && (
        <div className="text-[11px] text-gray-500 font-mono bg-gray-50 border border-gray-100 rounded px-3 py-1.5">
          Meds · {medConfirmNote}
        </div>
      )}

      <TodayBlockersCard
        blockers={vm.blockers}
        onResolveBlocker={handleResolveBlocker}
      />

      <TodayCompletionCard items={vm.completion} />

      <TodayTrustCard
        trust={vm.trust}
        onRefreshGarmin={() => {
          setPendingActionId('refresh-garmin');
          garminRefreshMut.mutate();
        }}
        refreshPending={garminRefreshMut.isPending}
        lastRefreshNote={garminSyncOutcome?.note ?? null}
        refreshStatus={garminSyncOutcome?.status ?? null}
      />

      <p className="text-[10px] text-gray-400 font-mono text-center pt-2">
        Refresh Garmin triggers an on-demand sync.
      </p>
    </div>
  );
}
