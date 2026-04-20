import type { CompletionStatus, TodayCompletionItemVM } from '../types';

interface Props {
  items: TodayCompletionItemVM[];
}

const STATUS_DOT: Record<CompletionStatus, string> = {
  complete: 'bg-emerald-400',
  partial: 'bg-amber-400',
  missing: 'bg-gray-300',
  blocked: 'bg-red-400',
  not_applicable: 'bg-gray-200',
};

const STATUS_LABEL: Record<CompletionStatus, string> = {
  complete: 'done',
  partial: 'partial',
  missing: 'pending',
  blocked: 'blocked',
  not_applicable: 'n/a',
};

const KIND_LABELS: Record<string, string> = {
  check_in: 'Check-in',
  check_out: 'Check-out',
  medication: 'Medication',
  temperature: 'Temperature',
  symptoms: 'Symptoms',
  weight: 'Weight',
  garmin: 'Garmin',
};

function kindLabel(k: string): string {
  return KIND_LABELS[k] ?? k.replace('_', ' ');
}

export default function TodayCompletionCard({ items }: Props) {
  const visible = items.filter((i) => i.required || i.status !== 'not_applicable');
  const requiredTotal = items.filter((i) => i.required).length;
  const requiredDone = items.filter(
    (i) => i.required && (i.status === 'complete' || i.status === 'not_applicable'),
  ).length;

  return (
    <section
      data-testid="today-completion"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-900">Protocol completion</h2>
        <span className="text-[11px] text-gray-400 font-mono">
          {requiredDone}/{requiredTotal} required
        </span>
      </div>
      <ul className="space-y-1.5">
        {visible.map((i) => (
          <li key={i.kind} className="flex items-center gap-2 text-xs">
            <span
              className={`w-1.5 h-1.5 rounded-full inline-block flex-shrink-0 ${STATUS_DOT[i.status]}`}
              aria-hidden
            />
            <span className="text-gray-700 w-24 flex-shrink-0">{kindLabel(i.kind)}</span>
            <span className="text-gray-400 font-mono w-16 flex-shrink-0">
              {STATUS_LABEL[i.status]}
            </span>
            <span className="text-gray-500 truncate">{i.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
