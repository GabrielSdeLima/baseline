import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createCheckpoint,
  createSymptomLog,
  createMedicationLog,
  createMeasurement,
  fetchActiveRegimens,
  nowISO,
  localToISO,
  toDatetimeLocal,
  todayISO,
} from '../api/client';
import { getUserId } from '../config';

type Tab = 'checkpoint' | 'symptom' | 'medlog' | 'measurement';

const SYMPTOM_SLUGS = [
  { slug: 'headache', label: 'Headache' },
  { slug: 'fatigue', label: 'Fatigue' },
  { slug: 'knee_pain', label: 'Knee pain' },
  { slug: 'lower_back_pain', label: 'Lower back pain' },
  { slug: 'nausea', label: 'Nausea' },
  { slug: 'insomnia', label: 'Insomnia' },
];

const MANUAL_METRICS = [
  { slug: 'body_temperature', label: 'Body Temperature', unit: '°C', step: '0.1', min: '34', max: '42' },
];

function ScoreRow({ value, onChange, label }: { value: number | null; onChange: (v: number) => void; label: string }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <div className="flex gap-1">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`w-7 h-7 text-xs rounded transition-colors ${
              value === n
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

function CheckpointForm({ onSuccess }: { onSuccess: () => void }) {
  const now = new Date();
  const userId = getUserId();
  const qc = useQueryClient();

  const [type, setType] = useState<'morning' | 'night'>(now.getHours() < 14 ? 'morning' : 'night');
  const [date, setDate] = useState(todayISO());
  const [energy, setEnergy] = useState<number | null>(null);
  const [mood, setMood] = useState<number | null>(null);
  const [sleepQ, setSleepQ] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');

  const mut = useMutation({
    mutationFn: () => {
      const at = new Date(`${date}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`).toISOString();
      return createCheckpoint({
        user_id: userId,
        checkpoint_type: type,
        checkpoint_date: date,
        checkpoint_at: at,
        energy: energy ?? null,
        mood: mood ?? null,
        sleep_quality: sleepQ ?? null,
        body_state_score: null,
        notes: notes || null,
        recorded_at: nowISO(),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['checkpoints'] });
      qc.invalidateQueries({ queryKey: ['summary', userId] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(''); mut.mutate(); }} className="space-y-4">
      <div className="flex gap-2">
        {(['morning', 'night'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            className={`flex-1 py-1.5 text-xs rounded transition-colors ${
              type === t ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {t === 'morning' ? '☀ Morning' : '☾ Night'}
          </button>
        ))}
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Date</label>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="w-full text-sm border-gray-200 rounded"
        />
      </div>

      {/* Morning: sleep quality first, then energy + mood */}
      {type === 'morning' && (
        <>
          <ScoreRow value={sleepQ} onChange={setSleepQ} label="Sleep quality" />
          <ScoreRow value={energy} onChange={setEnergy} label="Energy" />
          <ScoreRow value={mood} onChange={setMood} label="Mood" />
        </>
      )}

      {/* Night: energy + mood only (no sleep quality) */}
      {type === 'night' && (
        <>
          <ScoreRow value={energy} onChange={setEnergy} label="Energy" />
          <ScoreRow value={mood} onChange={setMood} label="Mood" />
        </>
      )}

      <div>
        <label className="block text-xs text-gray-500 mb-1">Notes (optional)</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full text-sm border-gray-200 rounded resize-none"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={mut.isPending}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {mut.isPending ? 'Saving…' : 'Save checkpoint'}
      </button>
    </form>
  );
}

function SymptomForm({ onSuccess }: { onSuccess: () => void }) {
  const userId = getUserId();
  const qc = useQueryClient();
  const now = new Date();

  const [slug, setSlug] = useState(SYMPTOM_SLUGS[0].slug);
  const [intensity, setIntensity] = useState<number | null>(5);
  const [showTime, setShowTime] = useState(false);
  const [startedAt, setStartedAt] = useState(toDatetimeLocal(now));
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');

  const mut = useMutation({
    mutationFn: () =>
      createSymptomLog({
        user_id: userId,
        symptom_slug: slug,
        intensity: intensity ?? 5,
        started_at: localToISO(startedAt),
        notes: notes || null,
        recorded_at: nowISO(),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['symptomLogs'] });
      qc.invalidateQueries({ queryKey: ['summary', userId] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(''); mut.mutate(); }} className="space-y-4">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Symptom</label>
        <select
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          className="w-full text-sm border-gray-200 rounded"
        >
          {SYMPTOM_SLUGS.map((s) => (
            <option key={s.slug} value={s.slug}>{s.label}</option>
          ))}
        </select>
      </div>

      <ScoreRow value={intensity} onChange={setIntensity} label="Intensity" />

      <div>
        {showTime ? (
          <>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-gray-500">Started at</label>
              <button
                type="button"
                onClick={() => setShowTime(false)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                use now
              </button>
            </div>
            <input
              type="datetime-local"
              value={startedAt}
              onChange={(e) => setStartedAt(e.target.value)}
              className="w-full text-sm border-gray-200 rounded"
            />
          </>
        ) : (
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">Started at: now</span>
            <button
              type="button"
              onClick={() => setShowTime(true)}
              className="text-xs text-gray-500 hover:text-gray-700 underline underline-offset-2"
            >
              edit time
            </button>
          </div>
        )}
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Notes (optional)</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full text-sm border-gray-200 rounded resize-none"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={mut.isPending}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {mut.isPending ? 'Saving…' : 'Log symptom'}
      </button>
    </form>
  );
}

function MedLogForm({ onSuccess }: { onSuccess: () => void }) {
  const userId = getUserId();
  const qc = useQueryClient();
  const now = new Date();

  const { data: regimens, isLoading } = useQuery({
    queryKey: ['activeRegimens', userId],
    queryFn: () => fetchActiveRegimens(userId),
    enabled: !!userId,
  });

  const [regimenId, setRegimenId] = useState('');
  const [status, setStatus] = useState<'taken' | 'skipped' | 'delayed'>('taken');
  const [takenAt, setTakenAt] = useState(toDatetimeLocal(now));
  const [error, setError] = useState('');

  const items = regimens?.items ?? [];

  const mut = useMutation({
    mutationFn: () => {
      const selectedId = regimenId || items[0]?.id;
      if (!selectedId) throw new Error('No regimen selected');
      return createMedicationLog({
        user_id: userId,
        regimen_id: selectedId,
        status,
        scheduled_at: nowISO(),
        taken_at: status !== 'skipped' ? localToISO(takenAt) : null,
        recorded_at: nowISO(),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['medLogs'] });
      qc.invalidateQueries({ queryKey: ['summary', userId] });
      qc.invalidateQueries({ queryKey: ['adherence', userId] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  if (isLoading) return <p className="text-xs text-gray-400">Loading regimens…</p>;
  if (!items.length) {
    return (
      <div className="space-y-2 py-1">
        <p className="text-xs text-gray-600 font-medium">No active medication regimens</p>
        <p className="text-xs text-gray-400">
          Go to the <span className="font-medium text-gray-600">Meds</span> tab in the navigation bar to create one.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(''); mut.mutate(); }} className="space-y-4">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Medication</label>
        <select
          value={regimenId || items[0]?.id}
          onChange={(e) => setRegimenId(e.target.value)}
          className="w-full text-sm border-gray-200 rounded"
        >
          {items.map((r) => (
            <option key={r.id} value={r.id}>
              {r.medication_name} — {r.dosage_amount} {r.dosage_unit}
            </option>
          ))}
        </select>
      </div>

      <div className="flex gap-2">
        {(['taken', 'skipped', 'delayed'] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={`flex-1 py-1.5 text-xs rounded capitalize transition-colors ${
              status === s ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {status !== 'skipped' && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            {status === 'taken' ? 'Taken at' : 'Delayed until'}
          </label>
          <input
            type="datetime-local"
            value={takenAt}
            onChange={(e) => setTakenAt(e.target.value)}
            className="w-full text-sm border-gray-200 rounded"
          />
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={mut.isPending}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {mut.isPending ? 'Saving…' : 'Log medication'}
      </button>
    </form>
  );
}

function MeasurementForm({ onSuccess }: { onSuccess: () => void }) {
  const userId = getUserId();
  const qc = useQueryClient();
  const now = new Date();

  const [metricIdx, setMetricIdx] = useState(0);
  const [value, setValue] = useState('');
  const [measuredAt, setMeasuredAt] = useState(toDatetimeLocal(now));
  const [error, setError] = useState('');

  const metric = MANUAL_METRICS[metricIdx];

  const mut = useMutation({
    mutationFn: () => {
      const v = parseFloat(value);
      if (isNaN(v)) throw new Error('Invalid value');
      return createMeasurement({
        user_id: userId,
        metric_type_slug: metric.slug,
        source_slug: 'manual',
        value_num: v,
        unit: metric.unit,
        measured_at: localToISO(measuredAt),
        recorded_at: nowISO(),
        aggregation_level: 'spot',
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['measurements'] });
      qc.invalidateQueries({ queryKey: ['summary', userId] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(''); mut.mutate(); }} className="space-y-4">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Metric</label>
        <select
          value={metricIdx}
          onChange={(e) => { setMetricIdx(Number(e.target.value)); setValue(''); }}
          className="w-full text-sm border-gray-200 rounded"
        >
          {MANUAL_METRICS.map((m, i) => (
            <option key={m.slug} value={i}>{m.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Value ({metric.unit})
        </label>
        <div className="flex gap-2">
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            step={metric.step}
            min={metric.min}
            max={metric.max}
            placeholder="e.g. 37.0"
            className="flex-1 text-sm border-gray-200 rounded"
            required
          />
          <span className="flex items-center text-sm text-gray-400 font-mono px-2">
            {metric.unit}
          </span>
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Measured at</label>
        <input
          type="datetime-local"
          value={measuredAt}
          onChange={(e) => setMeasuredAt(e.target.value)}
          className="w-full text-sm border-gray-200 rounded"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={mut.isPending}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {mut.isPending ? 'Saving…' : 'Save measurement'}
      </button>
    </form>
  );
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'checkpoint', label: 'Check-in' },
  { id: 'symptom', label: 'Symptom' },
  { id: 'medlog', label: 'Med Log' },
  { id: 'measurement', label: 'Measure' },
];

export default function QuickInputModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('checkpoint');
  const [success, setSuccess] = useState(false);

  const handleSuccess = () => {
    setSuccess(true);
    setTimeout(() => { setSuccess(false); onClose(); }, 1200);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-t-2xl sm:rounded-xl w-full sm:max-w-md max-h-[90vh] overflow-y-auto shadow-xl">
        <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Quick Input</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg leading-none">&#x2715;</button>
        </div>

        <div className="flex gap-1 px-4 pt-3 pb-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1 text-xs rounded-full transition-colors ${
                tab === t.id
                  ? 'bg-gray-900 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="px-4 py-4">
          {success ? (
            <div className="text-center py-6">
              <p className="text-green-600 font-medium text-sm">&#x2713; Saved</p>
            </div>
          ) : (
            <>
              {tab === 'checkpoint' && <CheckpointForm onSuccess={handleSuccess} />}
              {tab === 'symptom' && <SymptomForm onSuccess={handleSuccess} />}
              {tab === 'medlog' && <MedLogForm onSuccess={handleSuccess} />}
              {tab === 'measurement' && <MeasurementForm onSuccess={handleSuccess} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
