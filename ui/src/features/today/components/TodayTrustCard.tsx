import type { GarminSyncStatus } from '../../../api/types';
import type { TodayTrustVM, TrustStatus } from '../types';

interface Props {
  trust: TodayTrustVM;
  onRefreshGarmin: () => void;
  refreshPending?: boolean;
  /** Non-null if the Garmin refresh was ever attempted — drives the hint text. */
  lastRefreshNote?: string | null;
  /** Server-reported outcome of the last refresh; drives the note colour. */
  refreshStatus?: GarminSyncStatus | null;
}

const DOT: Record<TrustStatus, string> = {
  ok: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  unknown: 'bg-gray-300',
};

const LABEL: Record<TrustStatus, string> = {
  ok: 'trusted',
  degraded: 'degraded',
  unknown: 'unknown',
};

const NOTE_COLOUR: Record<GarminSyncStatus, string> = {
  completed: 'text-emerald-600',
  no_new_data: 'text-gray-500',
  already_running: 'text-amber-600',
  failed: 'text-red-600',
};

export default function TodayTrustCard({
  trust,
  onRefreshGarmin,
  refreshPending,
  lastRefreshNote,
  refreshStatus,
}: Props) {
  return (
    <section
      data-testid="today-trust"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-900">Data trust</h2>
        <span className="flex items-center gap-1.5 text-[11px] font-mono">
          <span className={`w-1.5 h-1.5 rounded-full inline-block ${DOT[trust.status]}`} aria-hidden />
          <span className="text-gray-500">{LABEL[trust.status]}</span>
        </span>
      </div>
      <p className="text-xs text-gray-600">{trust.detail}</p>
      <div className="flex items-center gap-3 mt-3">
        <button
          type="button"
          onClick={onRefreshGarmin}
          disabled={refreshPending}
          className="text-[11px] px-2.5 py-1 border border-gray-200 rounded hover:border-gray-400 text-gray-700 hover:text-gray-900 disabled:opacity-50 transition-colors"
        >
          {refreshPending ? 'Refreshing…' : 'Refresh Garmin'}
        </button>
        {lastRefreshNote && (
          <span
            data-testid="garmin-sync-note"
            data-status={refreshStatus ?? undefined}
            className={`text-[10px] font-mono ${
              refreshStatus ? NOTE_COLOUR[refreshStatus] : 'text-gray-400'
            }`}
          >
            {lastRefreshNote}
          </span>
        )}
      </div>
    </section>
  );
}
