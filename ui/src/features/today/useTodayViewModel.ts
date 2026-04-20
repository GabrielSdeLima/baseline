import { useMemo } from 'react';
import { todayISO } from '../../api/client';
import { deriveTodayViewModel } from './deriveTodayViewModel';
import { useTodaySources, type SourceQueryError } from './useTodaySources';
import { defaultDailyProtocol } from './types';
import type { DailyProtocol, TodayViewModel } from './types';

export interface UseTodayViewModelParams {
  userId: string;
  /** Defaults to today (local). */
  date?: string;
  /** Injection point for a future backend-driven protocol. */
  protocol?: DailyProtocol;
}

export interface UseTodayViewModelResult {
  vm: TodayViewModel;
  /** True only on first paint, before any source has loaded. */
  isLoading: boolean;
  /** True only when every source query failed. */
  isFullyErrored: boolean;
  queryErrors: SourceQueryError[];
}

export function useTodayViewModel(params: UseTodayViewModelParams): UseTodayViewModelResult {
  const date = params.date ?? todayISO();
  const { sources, isLoading, isFullyErrored, queryErrors } = useTodaySources({
    userId: params.userId,
    date,
  });

  const protocol = params.protocol ?? defaultDailyProtocol(date);

  const vm = useMemo(
    () => deriveTodayViewModel(protocol, sources),
    [protocol, sources],
  );

  return { vm, isLoading, isFullyErrored, queryErrors };
}
