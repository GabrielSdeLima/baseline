import { formatDistanceToNowStrict, parseISO } from 'date-fns';
import InsightCard from './InsightCard';
import type { LatestScaleReading, ScaleMetric } from '../api/types';

interface Props {
  data: LatestScaleReading | undefined;
  isLoading: boolean;
  error: Error | null;
}

function toNumber(m: ScaleMetric | undefined, digits: number): string | null {
  if (!m) return null;
  const n = Number(m.value);
  if (!Number.isFinite(n)) return null;
  return n.toFixed(digits);
}

function relativeLabel(iso: string | null): string {
  if (!iso) return '';
  try {
    return `${formatDistanceToNowStrict(parseISO(iso))} ago`;
  } catch {
    return '';
  }
}

function Stat({
  label,
  value,
  unit,
}: {
  label: string;
  value: string | null;
  unit: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-gray-400">{label}</div>
      <div className="text-sm font-mono text-gray-900">
        {value ?? '—'}
        {value != null && <span className="text-gray-400 ml-0.5">{unit}</span>}
      </div>
    </div>
  );
}

export default function ScaleReadingCard({ data, isLoading, error }: Props) {
  return (
    <InsightCard title="Latest Scale Reading" stability="stable" isLoading={isLoading} error={error}>
      {data && <Content data={data} />}
    </InsightCard>
  );
}

function Content({ data }: { data: LatestScaleReading }) {
  if (data.status === 'never_measured') {
    return (
      <p className="text-sm text-gray-400">
        No readings yet
        <span className="block text-xs text-gray-400 mt-0.5">
          Use the Scan button above to capture a weighing.
        </span>
      </p>
    );
  }

  const m = data.metrics;
  const weight = toNumber(m.weight, 2);
  const bmi = toNumber(m.bmi, 1);

  if (data.status === 'weight_only') {
    const bmr = toNumber(m.bmr, 0);
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-mono text-gray-900">{weight ?? '—'}</span>
          <span className="text-sm text-gray-400">kg</span>
        </div>
        <p
          className="text-xs text-amber-600 mt-1"
          title={`decoder: ${data.decoder_version ?? 'unknown'}`}
        >
          Body composition not captured — feet may not have contacted electrodes.
        </p>
        {(bmi || bmr) && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
            <Stat label="BMI" value={bmi} unit="" />
            <Stat label="BMR" value={bmr} unit="kcal" />
          </div>
        )}
        <p className="text-[10px] text-gray-400 mt-3 font-mono">
          {relativeLabel(data.measured_at)}
        </p>
      </div>
    );
  }

  // full_reading
  const bf = toNumber(m.body_fat_pct, 1);
  const musclePct = toNumber(m.muscle_pct, 1);
  const waterPct = toNumber(m.water_pct, 1);

  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-mono text-gray-900">{weight ?? '—'}</span>
        <span className="text-sm text-gray-400">kg</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
        <Stat label="Body fat" value={bf} unit="%" />
        <Stat label="Muscle" value={musclePct} unit="%" />
        <Stat label="Water" value={waterPct} unit="%" />
        <Stat label="BMI" value={bmi} unit="" />
      </div>
      <p
        className="text-[10px] text-gray-400 mt-3"
        title={`Bioimpedance analysis — population-level regressions, not clinical truth. decoder: ${data.decoder_version ?? 'unknown'}`}
      >
        Body composition estimated from bioimpedance ·{' '}
        <span className="font-mono">{relativeLabel(data.measured_at)}</span>
      </p>
    </div>
  );
}
