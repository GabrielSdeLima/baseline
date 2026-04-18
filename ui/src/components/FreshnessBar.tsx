import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { isToday, isYesterday, parseISO, format } from 'date-fns';
import {
  fetchMeasurements,
  fetchCheckpoints,
  fetchSystemStatus,
  scanScale,
  todayISO,
} from '../api/client';
import { loadScaleProfile } from '../lib/scaleProfile';
import { loadScaleDevice } from '../lib/scaleDevice';
import type { SystemAgentSummary } from '../api/types';

const SCAN_TIMEOUT_S = 45;

function dotClass(dateStr: string | null): string {
  if (!dateStr) return 'bg-gray-300';
  const d = parseISO(dateStr);
  if (isToday(d)) return 'bg-green-400';
  if (isYesterday(d)) return 'bg-amber-400';
  return 'bg-gray-300';
}

function dateLabel(dateStr: string | null): string {
  if (!dateStr) return 'no data';
  const d = parseISO(dateStr);
  if (isToday(d)) return 'today';
  if (isYesterday(d)) return 'yesterday';
  return format(d, 'MMM d');
}

function SourceChip({ label, dateStr }: { label: string; dateStr: string | null }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 ${dotClass(dateStr)}`} />
      <span className="text-gray-500">{label}</span>
      <span className={dateStr ? 'text-gray-700' : 'text-gray-400'}>{dateLabel(dateStr)}</span>
    </span>
  );
}

function SourceTag({ syncAt, advancedAt }: { syncAt: string | null; advancedAt: string | null }) {
  if (!syncAt && !advancedAt) return null;
  return (
    <span className="text-[9px] text-gray-400 font-mono ml-1 flex items-center gap-1">
      {syncAt && <span>sync {dateLabel(syncAt)}</span>}
      {syncAt && advancedAt && <span>·</span>}
      {advancedAt && <span>data {dateLabel(advancedAt)}</span>}
    </span>
  );
}

function AgentChip({ agent }: { agent: SystemAgentSummary }) {
  const dotColor =
    agent.status === 'active'
      ? 'bg-green-400'
      : agent.status === 'stale'
      ? 'bg-amber-400'
      : 'bg-gray-300';
  return (
    <span className="flex items-center gap-1">
      <span className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 ${dotColor}`} />
      <span className="text-gray-600">{agent.display_name ?? agent.agent_type}</span>
    </span>
  );
}

interface Props {
  userId: string;
}

export default function FreshnessBar({ userId }: Props) {
  const today = todayISO();
  const qc = useQueryClient();
  const [scaleMsg, setScaleMsg] = useState('');
  const [countdown, setCountdown] = useState<number | null>(null);
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
      setScaleMsg(data.message);
      qc.invalidateQueries({ queryKey: ['freshness-scale'] });
      qc.invalidateQueries({ queryKey: ['measurements'] });
      qc.invalidateQueries({ queryKey: ['scale-latest'] });
      setTimeout(() => setScaleMsg(''), 5000);
    },
    onError: (e: Error) => {
      if (e.name !== 'AbortError') {
        setScaleMsg(e.message);
        setTimeout(() => setScaleMsg(''), 8000);
      }
    },
  });

  useEffect(() => {
    if (!scaleMut.isPending) {
      setCountdown(null);
      return;
    }
    let remaining = SCAN_TIMEOUT_S;
    setCountdown(remaining);
    const id = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining <= 0 ? 0 : remaining);
      if (remaining <= 0) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [scaleMut.isPending]);

  function handleCancel() {
    abortRef.current?.abort();
    scaleMut.reset();
    setCountdown(null);
    setScaleMsg('');
  }

  const garminQ = useQuery({
    queryKey: ['freshness-garmin', userId],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 1),
    enabled: !!userId,
    staleTime: 2 * 60 * 1000,
  });

  const scaleQ = useQuery({
    queryKey: ['freshness-scale', userId],
    queryFn: () => fetchMeasurements(userId, 'weight', 1),
    enabled: !!userId,
    staleTime: 2 * 60 * 1000,
  });

  const checkpointQ = useQuery({
    queryKey: ['freshness-checkpoint', userId, today],
    queryFn: () => fetchCheckpoints(userId, today, today),
    enabled: !!userId,
    staleTime: 2 * 60 * 1000,
  });

  const systemStatusQ = useQuery({
    queryKey: ['system-status', userId],
    queryFn: () => fetchSystemStatus(userId),
    enabled: !!userId,
    staleTime: 60 * 1000,
  });

  const garminDate = garminQ.data?.items[0]?.measured_at?.slice(0, 10) ?? null;
  const scaleDate = scaleQ.data?.items[0]?.measured_at?.slice(0, 10) ?? null;

  const todayCheckpoints = checkpointQ.data?.items ?? [];
  const hasMorning = todayCheckpoints.some((c) => c.checkpoint_type === 'morning');
  const hasNight = todayCheckpoints.some((c) => c.checkpoint_type === 'night');
  const checkinLabel = hasMorning && hasNight
    ? 'morning + night'
    : hasMorning
    ? 'morning'
    : hasNight
    ? 'night'
    : null;

  const garminStatus = systemStatusQ.data?.sources.find((s) => s.source_slug === 'garmin_connect');
  const hc900Status = systemStatusQ.data?.sources.find((s) => s.source_slug === 'hc900_ble');
  const agents = systemStatusQ.data?.agents ?? [];

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs mb-4">
      <span className="flex items-center gap-1.5">
        <SourceChip label="Garmin last daily metric" dateStr={garminDate} />
        {garminStatus && (
          <SourceTag
            syncAt={garminStatus.last_sync_at}
            advancedAt={garminStatus.last_advanced_at}
          />
        )}
      </span>
      <span className="flex items-center gap-1.5">
        <SourceChip label="Scale" dateStr={scaleDate} />
        {hc900Status?.device_paired === false && (
          <span className="text-[9px] text-amber-400 font-mono ml-1">no device</span>
        )}
        <button
          onClick={() => scaleMut.mutate()}
          disabled={scaleMut.isPending}
          className="ml-1 px-1.5 py-0.5 text-[10px] font-medium border border-gray-200 rounded hover:border-gray-400 text-gray-500 hover:text-gray-900 disabled:opacity-50 transition-colors"
        >
          {scaleMut.isPending ? `Scanning… ${countdown ?? SCAN_TIMEOUT_S}s` : 'Scan'}
        </button>
        {scaleMut.isPending && (
          <button
            onClick={handleCancel}
            aria-label="Cancel scan"
            className="px-1 py-0.5 text-[10px] text-gray-400 hover:text-gray-700 transition-colors"
          >
            ✕
          </button>
        )}
      </span>
      {scaleMsg && (
        <span className={`text-[10px] ${scaleMut.isError ? 'text-red-400' : 'text-green-500'}`}>
          {scaleMsg.slice(0, 80)}
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 ${
            checkinLabel ? 'bg-green-400' : 'bg-gray-300'
          }`}
        />
        <span className="text-gray-500">Manual check-in</span>
        <span className={checkinLabel ? 'text-gray-700' : 'text-gray-400'}>
          {checkinLabel ?? 'none today'}
        </span>
      </span>
      {agents.length > 0 && (
        <span className="w-full flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5 border-t border-gray-100 mt-0.5">
          <span className="text-gray-400">agents</span>
          {agents.map((a, i) => (
            <AgentChip key={i} agent={a} />
          ))}
        </span>
      )}
    </div>
  );
}
