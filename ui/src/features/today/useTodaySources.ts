import { useQuery } from '@tanstack/react-query';
import {
  fetchActiveRegimens,
  fetchCheckpoints,
  fetchLatestScaleReading,
  fetchMeasurements,
  fetchMedicationLogs,
  fetchSymptomLogs,
  fetchSystemStatus,
  nowISO,
  todayISO,
} from '../../api/client';
import type { MeasurementResponse } from '../../api/types';

import type { TodayRawSources } from './types';

export interface UseTodaySourcesParams {
  userId: string;
  /** Defaults to today (local). Use override for fixed-date debugging. */
  date?: string;
}

export interface SourceQueryError {
  source: string;
  error: Error;
}

export interface UseTodaySourcesResult {
  sources: TodayRawSources;
  /** True only until every query has resolved at least once (first paint). */
  isLoading: boolean;
  /** True if every query has failed — nothing to derive from. */
  isFullyErrored: boolean;
  /** Individual query failures, labelled. Empty when everything succeeded. */
  queryErrors: SourceQueryError[];
}

const STALE_SHORT = 60 * 1000;
const STALE_MEDIUM = 5 * 60 * 1000;

function onDate(items: readonly MeasurementResponse[] | undefined, date: string): MeasurementResponse[] {
  if (!items) return [];
  return items.filter((m) => (m.measured_at ?? '').slice(0, 10) === date);
}

export function useTodaySources(params: UseTodaySourcesParams): UseTodaySourcesResult {
  const userId = params.userId;
  const date = params.date ?? todayISO();
  const enabled = !!userId;

  const checkpointsQ = useQuery({
    queryKey: ['today-v2', 'checkpoints', userId, date],
    queryFn: () => fetchCheckpoints(userId, date, date),
    enabled,
    staleTime: STALE_SHORT,
  });

  const symptomsQ = useQuery({
    queryKey: ['today-v2', 'symptoms', userId],
    queryFn: () => fetchSymptomLogs(userId, 50),
    enabled,
    staleTime: STALE_SHORT,
  });

  const temperatureQ = useQuery({
    queryKey: ['today-v2', 'measurements', userId, 'body_temperature'],
    queryFn: () => fetchMeasurements(userId, 'body_temperature', 10),
    enabled,
    staleTime: STALE_SHORT,
  });

  const weightQ = useQuery({
    queryKey: ['today-v2', 'measurements', userId, 'weight'],
    queryFn: () => fetchMeasurements(userId, 'weight', 5),
    enabled,
    staleTime: STALE_SHORT,
  });

  const scaleLatestQ = useQuery({
    queryKey: ['today-v2', 'scale-latest', userId],
    queryFn: () => fetchLatestScaleReading(userId),
    enabled,
    staleTime: STALE_SHORT,
  });

  const hrvQ = useQuery({
    queryKey: ['today-v2', 'measurements', userId, 'hrv_rmssd'],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 14),
    enabled,
    staleTime: STALE_SHORT,
  });

  const rhrQ = useQuery({
    queryKey: ['today-v2', 'measurements', userId, 'resting_hr'],
    queryFn: () => fetchMeasurements(userId, 'resting_hr', 3),
    enabled,
    staleTime: STALE_SHORT,
  });

  const medLogsQ = useQuery({
    queryKey: ['today-v2', 'med-logs', userId, date],
    queryFn: () => fetchMedicationLogs(userId, date),
    enabled,
    staleTime: STALE_SHORT,
  });

  const regimensQ = useQuery({
    queryKey: ['today-v2', 'regimens', userId],
    queryFn: () => fetchActiveRegimens(userId),
    enabled,
    staleTime: STALE_MEDIUM,
  });

  const systemQ = useQuery({
    queryKey: ['today-v2', 'system-status', userId],
    queryFn: () => fetchSystemStatus(userId),
    enabled,
    staleTime: STALE_SHORT,
  });

  const labelled = [
    ['checkpoints', checkpointsQ],
    ['symptoms', symptomsQ],
    ['body_temperature', temperatureQ],
    ['weight', weightQ],
    ['scale-latest', scaleLatestQ],
    ['hrv', hrvQ],
    ['resting_hr', rhrQ],
    ['med-logs', medLogsQ],
    ['active-regimens', regimensQ],
    ['system-status', systemQ],
  ] as const;

  const isLoading = labelled.every(([, q]) => q.isLoading);
  const isFullyErrored =
    labelled.every(([, q]) => q.isError) && labelled.length > 0;
  const queryErrors: SourceQueryError[] = labelled
    .filter(([, q]) => q.isError && q.error)
    .map(([source, q]) => ({ source, error: q.error as Error }));

  const sources: TodayRawSources = {
    date,
    now: nowISO(),
    checkpointsToday: checkpointsQ.data?.items ?? [],
    symptomsActiveToday: (symptomsQ.data?.items ?? []).filter(
      (s) => (s.started_at ?? '').slice(0, 10) === date,
    ),
    temperatureToday: onDate(temperatureQ.data?.items, date),
    weightToday: onDate(weightQ.data?.items, date),
    latestScaleReading: scaleLatestQ.data ?? null,
    garminMetricsToday: [
      ...onDate(hrvQ.data?.items, date),
      ...onDate(rhrQ.data?.items, date),
    ],
    latestHrvMeasurement: hrvQ.data?.items[0] ?? null,
    medicationLogsToday: medLogsQ.data?.items ?? [],
    activeRegimens: regimensQ.data?.items ?? [],
    systemStatus: systemQ.data ?? null,
  };

  return { sources, isLoading, isFullyErrored, queryErrors };
}
