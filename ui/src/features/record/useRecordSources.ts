import { useQuery } from '@tanstack/react-query';
import {
  fetchCheckpoints,
  fetchLatestScaleReading,
  fetchMeasurements,
  fetchSymptomLogs,
  nowISO,
  todayISO,
} from '../../api/client';
import type { RecordRawSources } from './types';
import { localDateSubDays } from './deriveRecordViewModel';

export interface UseRecordSourcesResult {
  sources: RecordRawSources;
  isLoading: boolean;
  queryErrors: Array<{ source: string; error: Error }>;
}

const STALE = 5 * 60 * 1000;
const DEFAULT_WINDOW = 30;

export function useRecordSources(
  userId: string,
  windowDays = DEFAULT_WINDOW,
): UseRecordSourcesResult {
  const date = todayISO();
  const windowStart = localDateSubDays(date, windowDays - 1);
  const enabled = !!userId;

  const checkpointsQ = useQuery({
    queryKey: ['record', 'checkpoints', userId, windowStart, date],
    queryFn: () => fetchCheckpoints(userId, windowStart, date),
    enabled,
    staleTime: STALE,
  });

  const symptomsQ = useQuery({
    queryKey: ['record', 'symptoms', userId],
    queryFn: () => fetchSymptomLogs(userId, 200),
    enabled,
    staleTime: STALE,
  });

  const temperatureQ = useQuery({
    queryKey: ['record', 'temperature', userId],
    queryFn: () => fetchMeasurements(userId, 'temperature', windowDays),
    enabled,
    staleTime: STALE,
  });

  const scaleQ = useQuery({
    queryKey: ['record', 'scale', userId],
    queryFn: () => fetchLatestScaleReading(userId),
    enabled,
    staleTime: STALE,
  });

  const labelled = [
    ['checkpoints', checkpointsQ],
    ['symptoms', symptomsQ],
    ['temperature', temperatureQ],
    ['scale', scaleQ],
  ] as const;

  const isLoading = labelled.every(([, q]) => q.isLoading);
  const queryErrors = labelled
    .filter(([, q]) => q.isError && q.error)
    .map(([source, q]) => ({ source, error: q.error as Error }));

  const sources: RecordRawSources = {
    date,
    now: nowISO(),
    windowDays,
    checkpoints: checkpointsQ.data?.items ?? [],
    symptoms: symptomsQ.data?.items ?? [],
    temperature: temperatureQ.data?.items ?? [],
    scaleReading: scaleQ.data ?? null,
  };

  return { sources, isLoading, queryErrors };
}
