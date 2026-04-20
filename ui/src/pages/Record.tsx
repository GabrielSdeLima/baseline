import { useMemo, useState } from 'react';
import { getUserId } from '../config';
import { deriveRecordViewModel } from '../features/record/deriveRecordViewModel';
import { useRecordSources } from '../features/record/useRecordSources';
import type { RecordDayGroup, RecordEntry, RecordFilter } from '../features/record/types';

// ── Filter chip metadata ──────────────────────────────────────────────────

const FILTER_LABELS: Record<RecordFilter, string> = {
  all: 'All',
  checkpoint: 'Check-ins',
  symptom: 'Symptoms',
  temperature: 'Temperature',
  scale: 'Scale',
};

// ── Entry type badge label ────────────────────────────────────────────────

const TYPE_BADGE: Record<string, string> = {
  checkpoint: 'check',
  symptom: 'symptom',
  temperature: 'temp',
  scale: 'scale',
};

// ── Atoms ─────────────────────────────────────────────────────────────────

function FilterStrip({
  active,
  onChange,
}: {
  active: RecordFilter;
  onChange: (f: RecordFilter) => void;
}) {
  return (
    <div data-testid="record-filter-strip" className="flex gap-1.5 flex-wrap">
      {(Object.keys(FILTER_LABELS) as RecordFilter[]).map((f) => (
        <button
          key={f}
          data-testid={`record-chip-${f}`}
          aria-pressed={active === f}
          onClick={() => onChange(f)}
          className={`px-2.5 py-1 text-xs font-medium rounded-full transition-colors ${
            active === f
              ? 'bg-gray-900 text-white'
              : 'bg-white border border-gray-200 text-gray-500 hover:text-gray-900 hover:border-gray-400'
          }`}
        >
          {FILTER_LABELS[f]}
        </button>
      ))}
    </div>
  );
}

function EntryRow({
  entry,
  showScaleCaveat,
}: {
  entry: RecordEntry;
  showScaleCaveat: boolean;
}) {
  return (
    <div
      data-testid="record-entry"
      data-type={entry.type}
      className="py-2.5 flex items-start gap-3"
    >
      <span className="text-[10px] font-mono text-gray-400 uppercase mt-0.5 w-14 shrink-0 text-right leading-tight">
        {TYPE_BADGE[entry.type] ?? entry.type}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-800">{entry.label}</span>
          <span className="text-[11px] font-mono text-gray-500">{entry.summary}</span>
        </div>
        {entry.detail && (
          <p className="text-[11px] text-gray-400 mt-0.5 leading-snug">{entry.detail}</p>
        )}
        {entry.type === 'scale' && showScaleCaveat && (
          <p
            data-testid="record-scale-caveat"
            className="text-[10px] font-mono text-amber-600 mt-0.5"
          >
            Latest available scale reading
          </p>
        )}
      </div>
    </div>
  );
}

function DayGroup({
  group,
  scaleReadingIsHistorical,
}: {
  group: RecordDayGroup;
  scaleReadingIsHistorical: boolean;
}) {
  return (
    <section
      data-testid="record-day-group"
      data-date={group.date}
      className="bg-white border border-gray-200 rounded-lg overflow-hidden"
    >
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-50">
        <span
          className={`text-xs font-semibold font-mono ${
            group.isToday ? 'text-gray-900' : 'text-gray-600'
          }`}
        >
          {group.label}
          {group.isToday && (
            <span className="ml-1.5 text-[10px] text-gray-400 font-normal">·today</span>
          )}
        </span>
        <span className="text-[10px] font-mono text-gray-400">
          {group.entryCount} {group.entryCount === 1 ? 'entry' : 'entries'}
        </span>
      </div>
      <div className="px-4 divide-y divide-gray-50">
        {group.entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            showScaleCaveat={scaleReadingIsHistorical}
          />
        ))}
      </div>
    </section>
  );
}

function RecordSkeleton() {
  return (
    <div className="space-y-3" data-testid="record-loading">
      {[60, 80, 60].map((h, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 animate-pulse">
          <div className="h-3 bg-gray-100 rounded w-1/4 mb-3" />
          <div style={{ height: h }} className="bg-gray-100 rounded" />
        </div>
      ))}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────

export default function Record() {
  const userId = getUserId();
  const [filter, setFilter] = useState<RecordFilter>('all');
  const { sources, isLoading } = useRecordSources(userId);
  const vm = useMemo(() => deriveRecordViewModel(sources, filter), [sources, filter]);

  if (isLoading) return <RecordSkeleton />;

  return (
    <div data-testid="record-page" className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Record</h2>
          <p className="text-xs text-gray-500 mt-0.5">What was logged and when</p>
        </div>
        <span className="text-[10px] font-mono text-gray-400">last {vm.windowDays} days</span>
      </div>

      <FilterStrip active={filter} onChange={setFilter} />

      {vm.isEmpty ? (
        <div
          data-testid="record-empty"
          className="bg-white border border-gray-200 rounded-lg p-8 text-center"
        >
          <p className="text-xs text-gray-400">No records in this window</p>
          {filter !== 'all' && (
            <p className="text-[10px] text-gray-400 font-mono mt-1">
              Try{' '}
              <button className="underline" onClick={() => setFilter('all')}>
                All
              </button>{' '}
              to see everything
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {vm.dayGroups.map((group) => (
            <DayGroup
              key={group.date}
              group={group}
              scaleReadingIsHistorical={vm.scaleReadingIsHistorical}
            />
          ))}
        </div>
      )}

      <p className="text-[10px] text-gray-400 font-mono text-center pt-1">
        Record · last {vm.windowDays} days · manually logged and device-captured events
      </p>
    </div>
  );
}
