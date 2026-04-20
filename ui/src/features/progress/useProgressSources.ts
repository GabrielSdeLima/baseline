import { useQuery } from '@tanstack/react-query';
import {
  fetchCheckpoints,
  fetchMeasurements,
  fetchMedicationAdherence,
  fetchSymptomLogs,
  fetchSummary,
  fetchSystemStatus,
  nowISO,
  todayISO,
} from '../../api/client';
import type { ProgressRawSources } from './types';

export interface SourceQueryError {
  source: string;
  error: Error;
}

export interface UseProgressSourcesResult {
  sources: ProgressRawSources;
  isLoading: boolean;
  isFullyErrored: boolean;
  queryErrors: SourceQueryError[];
}

/** ISO date string for n calendar days before dateStr (local). */
function subDays(dateStr: string, n: number): string {
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

// Progress data is less time-sensitive than Today; 5-minute stale is fine.
const STALE = 5 * 60 * 1000;

export function useProgressSources(userId: string): UseProgressSourcesResult {
  const date = todayISO();
  const start14d = subDays(date, 13); // 13 days ago + today = 14 calendar days
  const enabled = !!userId;

  const checkpointsQ = useQuery({
    queryKey: ['progress', 'checkpoints', userId, date],
    queryFn: () => fetchCheckpoints(userId, start14d, date),
    enabled,
    staleTime: STALE,
  });

  const symptomsQ = useQuery({
    queryKey: ['progress', 'symptoms', userId],
    queryFn: () => fetchSymptomLogs(userId, 50),
    enabled,
    staleTime: STALE,
  });

  const adherenceQ = useQuery({
    queryKey: ['progress', 'adherence', userId],
    queryFn: () => fetchMedicationAdherence(userId),
    enabled,
    staleTime: STALE,
  });

  const hrvQ = useQuery({
    queryKey: ['progress', 'hrv', userId],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 14),
    enabled,
    staleTime: STALE,
  });

  const rhrQ = useQuery({
    queryKey: ['progress', 'rhr', userId],
    queryFn: () => fetchMeasurements(userId, 'resting_hr', 14),
    enabled,
    staleTime: STALE,
  });

  const summaryQ = useQuery({
    queryKey: ['progress', 'summary', userId],
    queryFn: () => fetchSummary(userId),
    enabled,
    staleTime: STALE,
  });

  const systemQ = useQuery({
    queryKey: ['progress', 'system-status', userId],
    queryFn: () => fetchSystemStatus(userId),
    enabled,
    staleTime: STALE,
  });

  const labelled = [
    ['checkpoints', checkpointsQ],
    ['symptoms', symptomsQ],
    ['medication-adherence', adherenceQ],
    ['hrv', hrvQ],
    ['resting-hr', rhrQ],
    ['summary', summaryQ],
    ['system-status', systemQ],
  ] as const;

  const isLoading = labelled.every(([, q]) => q.isLoading);
  const isFullyErrored = labelled.every(([, q]) => q.isError) && labelled.length > 0;
  const queryErrors: SourceQueryError[] = labelled
    .filter(([, q]) => q.isError && q.error)
    .map(([source, q]) => ({ source, error: q.error as Error }));

  // Filter symptoms to the 14-day window before handing to derivation
  const now = nowISO();
  const cutoff14d = new Date(now).getTime() - 14 * 24 * 60 * 60 * 1000;
  const symptoms14d = (symptomsQ.data?.items ?? []).filter(
    (s) => new Date(s.started_at).getTime() > cutoff14d,
  );

  const sources: ProgressRawSources = {
    date,
    now,
    checkpoints14d: checkpointsQ.data?.items ?? [],
    symptoms14d,
    medicationAdherence: adherenceQ.data ?? null,
    hrv14d: hrvQ.data?.items ?? [],
    rhr14d: rhrQ.data?.items ?? [],
    summary: summaryQ.data ?? null,
    systemStatus: systemQ.data ?? null,
  };

  return { sources, isLoading, isFullyErrored, queryErrors };
}
