import type { TodayActionVM } from '../types';
import { useDemoMode } from '../../../context/DemoContext';

interface Props {
  actions: TodayActionVM[];
  onExecuteAction: (actionId: string) => void;
  actionPending?: string;
}

function formatDrivers(drivers: TodayActionVM['priorityDrivers']): string {
  return drivers.map((d) => d.replace('_', ' ')).join(' · ');
}

export default function TodayActionsList({ actions, onExecuteAction, actionPending }: Props) {
  const { isDemo } = useDemoMode();

  if (actions.length === 0) {
    return (
      <section
        data-testid="today-actions"
        className="bg-white border border-gray-200 rounded-lg p-4"
      >
        <h2 className="text-sm font-semibold text-gray-900 mb-1">Next actions</h2>
        <p className="text-xs text-gray-400">Nothing pending.</p>
      </section>
    );
  }

  return (
    <section
      data-testid="today-actions"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <h2 className="text-sm font-semibold text-gray-900 mb-3">Next actions</h2>
      <ol className="space-y-2">
        {actions.map((a) => (
          <li
            key={a.id}
            className="flex items-center justify-between gap-3 border border-gray-100 rounded px-3 py-2"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-gray-400">#{a.rank + 1}</span>
                <span className="text-sm text-gray-900 truncate">{a.label}</span>
                {a.timeSensitive && (
                  <span className="text-[9px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">
                    time
                  </span>
                )}
              </div>
              <p className="text-[11px] text-gray-400 mt-0.5 font-mono">
                {isDemo ? a.reason : `${a.reason} · ${formatDrivers(a.priorityDrivers)}`}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onExecuteAction(a.id)}
              disabled={actionPending === a.id}
              className="text-xs px-2.5 py-1.5 border border-gray-200 rounded hover:border-gray-400 text-gray-700 hover:text-gray-900 disabled:opacity-50 transition-colors flex-shrink-0"
            >
              {actionPending === a.id ? '…' : 'Do'}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
