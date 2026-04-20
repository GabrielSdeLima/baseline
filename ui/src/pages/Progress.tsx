import { useMemo } from 'react';
import { getUserId } from '../config';
import { deriveProgressViewModel } from '../features/progress/deriveProgressViewModel';
import { useProgressSources } from '../features/progress/useProgressSources';
import type {
  ConsistencyBlock,
  DataConfidenceBlock,
  ProgressOverallState,
  ProgressViewModel,
  ReportedSymptomBurdenBlock,
  SignalDirectionBlock,
  SignalTrend,
} from '../features/progress/types';

// ── Atoms ─────────────────────────────────────────────────────────────────

function DirectionLabel({ direction }: { direction: 'up' | 'down' | 'stable' }) {
  if (direction === 'up')
    return <span className="font-mono text-emerald-600">↑ up</span>;
  if (direction === 'down')
    return <span className="font-mono text-rose-600">↓ down</span>;
  return <span className="font-mono text-gray-400">→ stable</span>;
}

function Caveat({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p className="text-[10px] font-mono text-amber-700 mt-2.5 leading-snug border-t border-amber-100 pt-2">
      {text}
    </p>
  );
}

function RowDash() {
  return <span className="text-xs text-gray-300 font-mono">—</span>;
}

// ── Signal trend row ──────────────────────────────────────────────────────

function SignalRow({
  label,
  testId,
  trend,
}: {
  label: string;
  testId: string;
  trend: SignalTrend | null;
}) {
  if (!trend) {
    return (
      <div className="flex items-center justify-between py-1">
        <span className="text-xs text-gray-500">{label}</span>
        <RowDash />
      </div>
    );
  }

  const { direction, recentMean, deltaPct, unit } = trend;
  const sign = deltaPct >= 0 ? '+' : '';

  return (
    <div className="flex items-center justify-between py-1" data-testid={testId}>
      <span className="text-xs text-gray-500">{label}</span>
      <span className="flex items-center gap-2 text-xs font-mono">
        <DirectionLabel direction={direction} />
        <span className="text-gray-700">
          {recentMean.toFixed(1)} {unit}
        </span>
        {direction !== 'stable' && (
          <span className="text-[10px] text-gray-400">
            {sign}
            {deltaPct.toFixed(1)}%
          </span>
        )}
      </span>
    </div>
  );
}

// ── Consistency row ───────────────────────────────────────────────────────

function ConsistencyRow({
  label,
  rate,
  windowDays,
}: {
  label: string;
  rate: number | null;
  windowDays: number;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-gray-500">{label}</span>
      {rate === null ? (
        <RowDash />
      ) : (
        <span className="text-xs font-mono text-gray-700">
          {Math.round(rate * windowDays)}/{windowDays} days · {Math.round(rate * 100)}%
        </span>
      )}
    </div>
  );
}

// ── State chip ────────────────────────────────────────────────────────────

const STATE_DOT: Record<ProgressOverallState, string> = {
  sufficient: 'bg-emerald-400',
  mixed: 'bg-amber-400',
  limited: 'bg-gray-300',
  no_data: 'bg-gray-200',
};

const STATE_LABEL: Record<ProgressOverallState, string> = {
  sufficient: 'Sufficient data',
  mixed: 'Mixed coverage',
  limited: 'Collecting data',
  no_data: 'No data',
};

// ── Block cards ───────────────────────────────────────────────────────────

function HeroCard({ vm }: { vm: ProgressViewModel }) {
  return (
    <section
      data-testid="progress-hero"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-900">Progress</h2>
        <span
          data-testid="progress-overall-state"
          data-state={vm.overallState}
          className="flex items-center gap-1.5 text-[11px] font-mono text-gray-500"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full inline-block ${STATE_DOT[vm.overallState]}`}
            aria-hidden
          />
          {STATE_LABEL[vm.overallState]}
        </span>
      </div>
      <p className="text-xs text-gray-600 leading-relaxed">{vm.headline}</p>
      <p className="text-[10px] text-gray-400 font-mono mt-2">Last 14 days</p>
    </section>
  );
}

function ConsistencyCard({ block }: { block: ConsistencyBlock }) {
  return (
    <section
      data-testid="progress-consistency"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Protocol consistency
      </h3>
      <div className="divide-y divide-gray-50">
        <ConsistencyRow label="Check-in" rate={block.checkInRate} windowDays={block.windowDays} />
        <ConsistencyRow label="Check-out" rate={block.checkOutRate} windowDays={block.windowDays} />
        {block.medicationAdherence !== null && (
          <div className="flex items-center justify-between py-1">
            <span className="text-xs text-gray-500">Medication</span>
            <span className="text-xs font-mono text-gray-700">
              {Math.round(block.medicationAdherence * 100)}%
            </span>
          </div>
        )}
      </div>
      <Caveat text={block.caveat} />
    </section>
  );
}

function SignalDirectionCard({ block }: { block: SignalDirectionBlock }) {
  return (
    <section
      data-testid="progress-signal"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Signal direction
        </h3>
        <span className="text-[10px] font-mono text-gray-400">7-day window</span>
      </div>
      <div className="divide-y divide-gray-50">
        <SignalRow label="HRV" testId="progress-signal-hrv" trend={block.hrv} />
        <SignalRow label="Resting HR" testId="progress-signal-rhr" trend={block.rhr} />
      </div>
      <Caveat text={block.caveat} />
    </section>
  );
}

function ReportedSymptomBurdenCard({ block }: { block: ReportedSymptomBurdenBlock }) {
  const directionEl =
    block.direction === 'insufficient_data' ? (
      <span className="text-xs text-gray-400 font-mono">insufficient data</span>
    ) : block.direction === 'unclear' ? (
      <span className="text-xs text-amber-600 font-mono">unclear</span>
    ) : (
      <DirectionLabel direction={
        block.direction === 'improving' ? 'down'
          : block.direction === 'worsening' ? 'up'
          : 'stable'
      } />
    );

  return (
    <section
      data-testid="progress-symptom"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Reported symptom burden
      </h3>
      <div className="divide-y divide-gray-50">
        <div className="flex items-center justify-between py-1">
          <span className="text-xs text-gray-500">Direction</span>
          <span data-testid="progress-symptom-direction">{directionEl}</span>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-xs text-gray-500">Recent 7d</span>
          <span className="text-xs font-mono text-gray-700">
            {block.recentCount} {block.recentCount === 1 ? 'log' : 'logs'}
          </span>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-xs text-gray-500">Prior 7d</span>
          <span className="text-xs font-mono text-gray-700">
            {block.priorCount} {block.priorCount === 1 ? 'log' : 'logs'}
          </span>
        </div>
        {block.topSymptom && (
          <div className="flex items-center justify-between py-1">
            <span className="text-xs text-gray-500">Most frequent</span>
            <span data-testid="progress-symptom-top" className="text-xs font-mono text-gray-700">
              {block.topSymptom}
            </span>
          </div>
        )}
      </div>
      <Caveat text={block.caveat} />
    </section>
  );
}

function DataConfidenceCard({ block }: { block: DataConfidenceBlock }) {
  function StatusDot({ ok }: { ok: boolean }) {
    return (
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-rose-400'}`}
        aria-hidden
      />
    );
  }

  return (
    <section
      data-testid="progress-confidence"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
        Data confidence
      </h3>

      <div data-testid="progress-confidence-freshness" className="mb-3">
        <p className="text-[10px] font-mono text-gray-400 uppercase mb-1.5">Freshness</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <StatusDot ok={block.freshness.garminOk} />
            <span className="text-xs text-gray-600">
              Garmin — {block.freshness.garminOk ? 'configured' : 'not configured or error'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <StatusDot ok={block.freshness.scaleOk} />
            <span className="text-xs text-gray-600">
              Scale — {block.freshness.scaleOk ? 'paired' : 'not paired'}
            </span>
          </div>
        </div>
      </div>

      <div data-testid="progress-confidence-analytical">
        <p className="text-[10px] font-mono text-gray-400 uppercase mb-1.5">Analytical coverage</p>
        <div className="space-y-1">
          {block.analyticalCoverage.totalBlocks > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">Analysis blocks</span>
              <span className="text-xs font-mono text-gray-700">
                {block.analyticalCoverage.blocksWithData}/{block.analyticalCoverage.totalBlocks} with data
              </span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">Check-in consistency</span>
            <span className="text-xs font-mono text-gray-700">
              {block.analyticalCoverage.checkInConsistent ? 'consistent' : 'below 50%'}
            </span>
          </div>
        </div>
      </div>

      <p className="text-[10px] font-mono text-gray-400 mt-3 border-t border-gray-50 pt-2">
        {block.summary}
      </p>
    </section>
  );
}

// ── Empty / limited state ─────────────────────────────────────────────────

const EMPTY_STATE_COPY: Record<'no_data' | 'limited', { heading: string; bullets: string[] }> = {
  no_data: {
    heading: 'What builds Progress',
    bullets: [
      'Log a morning check-in and night check-out each day.',
      'Garmin HRV and resting HR sync automatically — use Refresh Garmin on Today if missing.',
      'Scale weight syncs via Bluetooth from the Today page.',
    ],
  },
  limited: {
    heading: 'Still collecting data',
    bullets: [
      'HRV signal needs 3+ readings per 7-day window.',
      'Check-in consistency rate needs more days of logging.',
    ],
  },
};

function ProgressEmptyState({ state }: { state: 'no_data' | 'limited' }) {
  const { heading, bullets } = EMPTY_STATE_COPY[state];
  return (
    <section
      data-testid="progress-empty"
      className="bg-white border border-gray-200 rounded-lg p-4"
    >
      <p className="text-xs font-semibold text-gray-500 mb-2">{heading}</p>
      <ul className="space-y-1">
        {bullets.map((b, i) => (
          <li key={i} className="text-xs text-gray-600">
            · {b}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Loading skeleton ───────────────────────────────────────────────────────

function ProgressSkeleton() {
  return (
    <div className="space-y-3" data-testid="progress-loading">
      {[56, 40, 40, 40, 48].map((h, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 animate-pulse">
          <div className={`h-3 bg-gray-100 rounded w-1/3 mb-3`} />
          <div style={{ height: h }} className="bg-gray-100 rounded" />
        </div>
      ))}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────

export default function Progress() {
  const userId = getUserId();
  const { sources, isLoading } = useProgressSources(userId);
  const vm = useMemo(() => deriveProgressViewModel(sources), [sources]);

  if (isLoading) return <ProgressSkeleton />;

  const { overallState } = vm;

  return (
    <div className="space-y-3">
      <HeroCard vm={vm} />

      {overallState === 'no_data' && (
        <>
          {vm.reportedSymptomBurden.direction !== 'insufficient_data' && (
            <ReportedSymptomBurdenCard block={vm.reportedSymptomBurden} />
          )}
          <ProgressEmptyState state="no_data" />
        </>
      )}

      {overallState === 'limited' && (
        <>
          {vm.reportedSymptomBurden.direction !== 'insufficient_data' && (
            <ReportedSymptomBurdenCard block={vm.reportedSymptomBurden} />
          )}
          <DataConfidenceCard block={vm.dataConfidence} />
          <ProgressEmptyState state="limited" />
        </>
      )}

      {(overallState === 'mixed' || overallState === 'sufficient') && (
        <>
          <ConsistencyCard block={vm.consistency} />
          <SignalDirectionCard block={vm.signalDirection} />
          <ReportedSymptomBurdenCard block={vm.reportedSymptomBurden} />
          <DataConfidenceCard block={vm.dataConfidence} />
        </>
      )}

      <p className="text-[10px] text-gray-400 font-mono text-center pt-1">
        Progress · last 14 days · 7-day comparison window
      </p>
    </div>
  );
}
