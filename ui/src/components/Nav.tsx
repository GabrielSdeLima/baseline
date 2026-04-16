type View = 'today' | 'timeline' | 'medications';

const VIEW_LABELS: Record<View, string> = {
  today: 'Today',
  timeline: 'Timeline',
  medications: 'Meds',
};

interface Props {
  view: View;
  onViewChange: (v: View) => void;
  onOpenInput: () => void;
}

export default function Nav({ view, onViewChange, onOpenInput }: Props) {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
      <div className="max-w-2xl mx-auto px-4 h-12 flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-gray-900 tracking-tight">
          BASELINE
        </span>

        <nav className="flex gap-1">
          {(Object.keys(VIEW_LABELS) as View[]).map((v) => (
            <button
              key={v}
              onClick={() => onViewChange(v)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                view === v
                  ? 'bg-gray-900 text-white'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              {VIEW_LABELS[v]}
            </button>
          ))}
        </nav>

        <button
          onClick={onOpenInput}
          className="text-xs font-medium text-gray-500 hover:text-gray-900 border border-gray-200 rounded px-2 py-1 hover:border-gray-400 transition-colors"
        >
          + Input
        </button>
      </div>
    </header>
  );
}
