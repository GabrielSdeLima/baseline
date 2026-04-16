interface Props {
  signal: string;
  size?: 'sm' | 'md';
}

const CONFIG: Record<string, { icon: string; cls: string; label: string }> = {
  low:               { icon: '●', cls: 'text-green-600',  label: 'low' },
  recovered:         { icon: '●', cls: 'text-green-600',  label: 'recovered' },
  moderate:          { icon: '◐', cls: 'text-blue-600',   label: 'moderate' },
  recovering:        { icon: '◐', cls: 'text-blue-600',   label: 'recovering' },
  high:              { icon: '▲', cls: 'text-amber-600',  label: 'high' },
  strained:          { icon: '▲', cls: 'text-amber-600',  label: 'strained' },
  overreaching:      { icon: '⚠', cls: 'text-red-600',   label: 'overreaching' },
  insufficient_data: { icon: '···', cls: 'text-gray-400', label: 'establishing baseline' },
};

export default function SignalBadge({ signal, size = 'md' }: Props) {
  const cfg = CONFIG[signal] ?? { icon: '–', cls: 'text-gray-400', label: signal };
  const textSize = size === 'sm' ? 'text-xs' : 'text-sm';
  return (
    <span className={`font-mono font-medium ${textSize} ${cfg.cls}`}>
      {cfg.icon} {cfg.label}
    </span>
  );
}
