import type { AvailabilityStatus } from '../api/types';

/** Short, honest UI copy for each availability state. */
export const AVAILABILITY_COPY: Record<AvailabilityStatus, string> = {
  ok: '',
  no_data: 'No physiological data yet',
  no_data_today: 'No data for today',
  insufficient_data: 'Baseline still forming',
  stale_data: 'Data is stale',
  partial: 'Partial coverage',
  not_applicable: 'Not in use',
};

export function availabilityLabel(status: AvailabilityStatus): string {
  return AVAILABILITY_COPY[status] ?? status;
}
