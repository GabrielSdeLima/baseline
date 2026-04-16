import { useQuery } from '@tanstack/react-query';
import { getUserId } from '../config';
import {
  fetchSummary,
  fetchDeviations,
  fetchMedicationAdherence,
  fetchMeasurements,
  nDaysAgoISO,
  todayISO,
} from '../api/client';
import InsightCard from '../components/InsightCard';
import SignalBadge from '../components/SignalBadge';
import FreshnessBar from '../components/FreshnessBar';

type TrendDir = '↑' | '↓' | '→';

interface HrvTrend {
  dir: TrendDir;
  streakDays: number;
  latestMs: number | null;
}

function computeHrvTrend(items: Array<{ measured_at: string; value_num: number }>): HrvTrend | null {
  const sorted = [...items]
    .sort((a, b) => a.measured_at.localeCompare(b.measured_at))
    .map((m) => Number(m.value_num));
  if (sorted.length < 2) return null;
  const latest = sorted[sorted.length - 1];
  const prev = sorted.slice(0, -1);
  const prevAvg = prev.reduce((s, v) => s + v, 0) / prev.length;
  const pct = (latest - prevAvg) / prevAvg;
  const dir: TrendDir = pct > 0.03 ? '↑' : pct < -0.03 ? '↓' : '→';

  // Count consecutive days at same direction (each consecutive pair)
  let streak = 1;
  for (let i = sorted.length - 2; i >= 1; i--) {
    const d = sorted[i] - sorted[i - 1];
    const dDir: TrendDir = d / sorted[i - 1] > 0.03 ? '↑' : d / sorted[i - 1] < -0.03 ? '↓' : '→';
    if (dDir === dir) streak++;
    else break;
  }
  return { dir, streakDays: streak, latestMs: latest };
}

const METRIC_UNITS: Record<string, string> = {
  hrv_rmssd: 'ms',
  resting_hr: 'bpm',
  body_temperature: '°C',
  weight: 'kg',
  sleep_duration: 'min',
  sleep_score: '',
  steps: '',
  active_calories: 'kcal',
  stress_level: '',
  spo2: '%',
  respiratory_rate: 'brpm',
  body_battery: '',
};

export default function Today() {
  const userId = getUserId();
  const today = todayISO();
  const start14 = nDaysAgoISO(14);

  const summaryQ = useQuery({
    queryKey: ['summary', userId],
    queryFn: () => fetchSummary(userId),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const deviationsQ = useQuery({
    queryKey: ['deviations', userId, start14, today],
    queryFn: () => fetchDeviations(userId, start14, today),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const adherenceQ = useQuery({
    queryKey: ['adherence', userId],
    queryFn: () => fetchMedicationAdherence(userId),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const hrvCountQ = useQuery({
    queryKey: ['measurements', userId, 'hrv_rmssd', 14],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 14),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const summary = summaryQ.data;

  const baselineForming =
    !hrvCountQ.isLoading && (hrvCountQ.data?.total ?? 0) < 3;

  const hrvTrend = hrvCountQ.data?.items.length
    ? computeHrvTrend(hrvCountQ.data.items)
    : null;

  const todayDeviations = deviationsQ.data?.deviations.filter(
    (d) => d.day === today
  ) ?? [];

  const formatDelta = (d: {
    metric_slug: string;
    metric_name: string;
    value: number;
    z_score: number;
    delta_abs: number;
  }) => {
    const sign = d.delta_abs > 0 ? '+' : '';
    const z = Number(d.z_score).toFixed(1);
    const unit = METRIC_UNITS[d.metric_slug] ?? '';
    const unitStr = unit ? ` ${unit}` : '';
    return `${d.metric_name}  z=${z}  (${sign}${Math.round(Number(d.delta_abs))}${unitStr})`;
  };

  const noRegimens =
    !adherenceQ.isLoading && (adherenceQ.data?.items.length ?? 0) === 0;

  return (
    <div className="space-y-3">
      <FreshnessBar userId={userId} />

      {/* Illness Signal — Experimental */}
      <InsightCard
        title="Illness Signal"
        stability="experimental"
        method="baseline_deviation_v1"
        isLoading={summaryQ.isLoading}
        error={summaryQ.error as Error | null}
      >
        {summary && (
          <div>
            <SignalBadge signal={summary.illness_signal} />
            {summary.illness_signal === 'insufficient_data' ? (
              <p className="text-xs text-gray-400 mt-1">
                establishing baseline · fewer than 3 data points
              </p>
            ) : hrvTrend && (
              <p className="text-xs text-gray-400 mt-1 font-mono">
                HRV {hrvTrend.dir} {hrvTrend.streakDays}d
                {hrvTrend.latestMs != null && (
                  <span className="ml-1">· {Math.round(hrvTrend.latestMs)} ms</span>
                )}
              </p>
            )}
          </div>
        )}
      </InsightCard>

      {/* Recovery Status — Experimental */}
      <InsightCard
        title="Recovery Status"
        stability="experimental"
        method="load_hrv_heuristic_v1"
        isLoading={summaryQ.isLoading}
        error={summaryQ.error as Error | null}
      >
        {summary && (
          <div>
            <SignalBadge signal={summary.recovery_status} />
            {summary.recovery_status === 'insufficient_data' ? (
              <p className="text-xs text-gray-400 mt-1">
                establishing baseline · fewer than 3 data points
              </p>
            ) : hrvTrend && (
              <p className="text-xs text-gray-400 mt-1 font-mono">
                HRV {hrvTrend.dir} {hrvTrend.streakDays}d
                {hrvTrend.latestMs != null && (
                  <span className="ml-1">· {Math.round(hrvTrend.latestMs)} ms</span>
                )}
              </p>
            )}
          </div>
        )}
      </InsightCard>

      {/* Physiological Deviations — Stable */}
      <InsightCard
        title="Physiological Deviations"
        stability="stable"
        isLoading={summaryQ.isLoading || deviationsQ.isLoading || hrvCountQ.isLoading}
        error={(summaryQ.error ?? deviationsQ.error) as Error | null}
      >
        {summary && (
          <div>
            {baselineForming ? (
              <p className="text-sm text-gray-500">
                Baseline forming
                <span className="block text-xs text-gray-400 mt-0.5">
                  {hrvCountQ.data?.total ?? 0} of 3 HRV readings collected
                </span>
              </p>
            ) : (
              <>
                <p className="text-sm text-gray-900">
                  {summary.active_deviations === 0
                    ? 'All metrics within baseline'
                    : `${summary.active_deviations} metric${summary.active_deviations > 1 ? 's' : ''} outside baseline`}
                </p>
                {todayDeviations.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {todayDeviations.map((d) => (
                      <li key={d.metric_slug} className="text-xs font-mono text-gray-600">
                        · {formatDelta(d)}
                      </li>
                    ))}
                  </ul>
                )}
                {summary.active_deviations > 0 && todayDeviations.length === 0 && (
                  <p className="text-xs text-gray-400 mt-1">deviations in recent window, none today</p>
                )}
              </>
            )}
            <p className="text-xs text-gray-400 mt-2">
              threshold |z| &gt; {deviationsQ.data?.deviation_threshold ?? '2.0'} · {deviationsQ.data?.baseline_window_days ?? 14}d window
            </p>
          </div>
        )}
      </InsightCard>

      {/* Symptom Burden — Stable */}
      <InsightCard
        title="Symptom Burden"
        stability="stable"
        isLoading={summaryQ.isLoading}
        error={summaryQ.error as Error | null}
      >
        {summary && (
          <div>
            <p className="text-sm text-gray-900">
              {Number(summary.current_symptom_burden) === 0
                ? 'No symptoms today'
                : `Burden: ${Number(summary.current_symptom_burden).toFixed(1)}`}
            </p>
          </div>
        )}
      </InsightCard>

      {/* Medication Adherence — Stable */}
      <InsightCard
        title="Medication Adherence"
        stability="stable"
        isLoading={adherenceQ.isLoading}
        error={adherenceQ.error as Error | null}
      >
        <div>
          {noRegimens ? (
            <p className="text-sm text-gray-400">No active regimens</p>
          ) : (
            <p className="text-sm text-gray-900">
              {Number(adherenceQ.data?.overall_adherence_pct ?? 0).toFixed(0)}% overall
            </p>
          )}
        </div>
      </InsightCard>
    </div>
  );
}
