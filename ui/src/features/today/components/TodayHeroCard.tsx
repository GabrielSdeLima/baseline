import type { TodayViewModel } from '../types';

interface Props {
  vm: TodayViewModel;
  onExecuteAction: (actionId: string) => void;
  onResolveBlocker: (blockerId: string) => void;
  actionPending?: string;
}

const STATE_PALETTE: Record<TodayViewModel['state'], { ring: string; tag: string; tagText: string }> = {
  ok: { ring: 'border-emerald-200', tag: 'bg-emerald-50', tagText: 'text-emerald-700' },
  action_needed: { ring: 'border-amber-200', tag: 'bg-amber-50', tagText: 'text-amber-700' },
  blocked: { ring: 'border-red-200', tag: 'bg-red-50', tagText: 'text-red-700' },
};

export default function TodayHeroCard({
  vm,
  onExecuteAction,
  onResolveBlocker,
  actionPending,
}: Props) {
  const palette = STATE_PALETTE[vm.state];
  const hero = vm.hero;

  return (
    <section
      data-testid="today-hero"
      className={`bg-white border ${palette.ring} rounded-lg p-4 shadow-sm`}
    >
      <div className="flex items-center justify-between mb-2">
        <span
          className={`text-[10px] uppercase tracking-wider font-mono px-2 py-0.5 rounded ${palette.tag} ${palette.tagText}`}
        >
          {vm.state.replace('_', ' ')}
        </span>
        <span className="text-[10px] text-gray-400 font-mono">{vm.date}</span>
      </div>

      <h1 className="text-lg font-semibold text-gray-900 leading-snug">{vm.headline}</h1>
      {vm.subheadline && <p className="text-xs text-gray-500 mt-1">{vm.subheadline}</p>}

      {hero.kind === 'action' && (
        <div className="mt-4">
          <p className="text-xs text-gray-500 mb-2">Next action</p>
          <button
            type="button"
            onClick={() => onExecuteAction(hero.action.id)}
            disabled={actionPending === hero.action.id}
            className="w-full bg-gray-900 text-white text-sm py-2.5 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {actionPending === hero.action.id ? 'Working…' : hero.action.label}
          </button>
          <p className="text-[11px] text-gray-400 mt-1.5 font-mono">{hero.action.reason}</p>
        </div>
      )}

      {hero.kind === 'blocked' && (
        <div className="mt-4">
          <p className="text-xs text-gray-500 mb-2">How to resolve</p>
          <p className="text-sm text-gray-800">{hero.blocker.resolutionHint}</p>
          <button
            type="button"
            onClick={() => onResolveBlocker(hero.blocker.id)}
            className="mt-3 text-xs font-medium text-gray-600 hover:text-gray-900 underline underline-offset-4"
          >
            Go to {hero.blocker.resolutionSurface}
          </button>
        </div>
      )}

      {hero.kind === 'confirmation' && hero.supportingSignal && (
        <p className="text-xs text-gray-400 mt-3 font-mono">
          {hero.supportingSignal.label}: {hero.supportingSignal.value}
        </p>
      )}
    </section>
  );
}
