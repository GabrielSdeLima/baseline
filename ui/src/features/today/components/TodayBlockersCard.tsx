import type { TodayBlockerVM } from '../types';
import { useDemoMode } from '../../../context/DemoContext';

interface Props {
  blockers: TodayBlockerVM[];
  onResolveBlocker: (blockerId: string) => void;
}

export default function TodayBlockersCard({ blockers, onResolveBlocker }: Props) {
  const { isDemo } = useDemoMode();

  if (blockers.length === 0) return null;

  return (
    <section
      data-testid="today-blockers"
      className="bg-white border border-red-200 rounded-lg p-4"
    >
      <h2 className="text-sm font-semibold text-red-700 mb-2">Blockers</h2>
      <ul className="space-y-2">
        {blockers.map((b) => (
          <li key={b.id} className="border border-red-100 rounded px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm text-gray-900">{b.message}</p>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  {b.resolutionHint}
                </p>
                {!isDemo && (
                  <p className="text-[10px] text-gray-400 mt-1 font-mono">
                    cause: {b.cause} · affects: {b.affects.join(', ')}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onResolveBlocker(b.id)}
                className="text-[11px] font-medium px-2.5 py-1 border border-red-200 rounded hover:border-red-400 text-red-700 transition-colors flex-shrink-0"
              >
                {b.resolutionSurface}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
