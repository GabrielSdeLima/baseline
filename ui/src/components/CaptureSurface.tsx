/**
 * CaptureSurface — the primary daily-logging surface.
 *
 * Replaces the old QuickInputModal.  Key differences:
 *   · Full-screen overlay — not a small centered modal.
 *   · Five explicit sections: Check-in, Temperature, Symptoms, Medication,
 *     Scale.  Opening from a Today action pre-selects the right section so
 *     the user lands exactly where they need to be.
 *   · Stays open after a successful save: shows "✓ Saved" for 1.5 s then
 *     resets the form so the user can log another item in the same session.
 *   · ESC dismisses.
 */
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createCheckpoint,
  createMeasurement,
  createMedicationLog,
  createSymptomLog,
  fetchActiveRegimens,
  localToISO,
  nowISO,
  scanScale,
  toDatetimeLocal,
  todayISO,
} from '../api/client';
import { getUserId } from '../config';
import { loadScaleDevice } from '../lib/scaleDevice';
import { loadScaleProfile } from '../lib/scaleProfile';

export type CaptureSection =
  | 'checkpoint'
  | 'measurement'
  | 'symptom'
  | 'medlog'
  | 'scale';

const SECTIONS: { id: CaptureSection; label: string }[] = [
  { id: 'checkpoint', label: 'Check-in' },
  { id: 'measurement', label: 'Temperature' },
  { id: 'symptom', label: 'Symptoms' },
  { id: 'medlog', label: 'Medication' },
  { id: 'scale', label: 'Scale' },
];

const SYMPTOM_SLUGS = [
  { slug: 'headache', label: 'Headache' },
  { slug: 'fatigue', label: 'Fatigue' },
  { slug: 'knee_pain', label: 'Knee pain' },
  { slug: 'lower_back_pain', label: 'Lower back pain' },
  { slug: 'nausea', label: 'Nausea' },
  { slug: 'insomnia', label: 'Insomnia' },
];

const TEMPERATURE_METRIC = {
  slug: 'body_temperature',
  unit: '°C',
  step: '0.1',
  min: '34',
  max: '42',
};

const SCAN_TIMEOUT_S = 45;

// ── Shared primitives ─────────────────────────────────────────────────────

function ScoreRow({
  value,
  onChange,
  label,
}: {
  value: number | null;
  onChange: (v: number) => void;
  label: string;
}) {
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

// ── Section forms ─────────────────────────────────────────────────────────

function CheckpointForm({ onSuccess }: { onSuccess: () => void }) {
  const now = new Date();
  const userId = getUserId();
  const qc = useQueryClient();

  const [type, setType] = useState<'morning' | 'night'>(
    now.getHours() < 14 ? 'morning' : 'night',
  );
  const [date, setDate] = useState(todayISO());
  const [energy, setEnergy] = useState<number | null>(null);
  const [mood, setMood] = useState<number | null>(null);
  const [sleepQ, setSleepQ] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');

  const mut = useMutation({
    mutationFn: () => {
      const at = new Date(
        `${date}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`,
      ).toISOString();
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
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form
      data-testid="capture-checkpoint-form"
      onSubmit={(e) => {
        e.preventDefault();
        setError('');
        mut.mutate();
      }}
      className="space-y-4"
    >
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

      {type === 'morning' && (
        <>
          <ScoreRow value={sleepQ} onChange={setSleepQ} label="Sleep quality" />
          <ScoreRow value={energy} onChange={setEnergy} label="Energy" />
          <ScoreRow value={mood} onChange={setMood} label="Mood" />
        </>
      )}

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
        {mut.isPending ? 'Saving…' : 'Save check-in'}
      </button>
    </form>
  );
}

function TemperatureForm({ onSuccess }: { onSuccess: () => void }) {
  const userId = getUserId();
  const qc = useQueryClient();
  const now = new Date();

  const [value, setValue] = useState('');
  const [measuredAt, setMeasuredAt] = useState(toDatetimeLocal(now));
  const [error, setError] = useState('');

  const mut = useMutation({
    mutationFn: () => {
      const v = parseFloat(value);
      if (isNaN(v)) throw new Error('Invalid value');
      return createMeasurement({
        user_id: userId,
        metric_type_slug: TEMPERATURE_METRIC.slug,
        source_slug: 'manual',
        value_num: v,
        unit: TEMPERATURE_METRIC.unit,
        measured_at: localToISO(measuredAt),
        recorded_at: nowISO(),
        aggregation_level: 'spot',
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['measurements'] });
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form
      data-testid="capture-temperature-form"
      onSubmit={(e) => {
        e.preventDefault();
        setError('');
        mut.mutate();
      }}
      className="space-y-4"
    >
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Temperature ({TEMPERATURE_METRIC.unit})
        </label>
        <div className="flex gap-2 items-center">
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            step={TEMPERATURE_METRIC.step}
            min={TEMPERATURE_METRIC.min}
            max={TEMPERATURE_METRIC.max}
            placeholder="e.g. 37.0"
            className="flex-1 text-sm border-gray-200 rounded"
            required
          />
          <span className="text-sm text-gray-400 font-mono px-2">{TEMPERATURE_METRIC.unit}</span>
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
        {mut.isPending ? 'Saving…' : 'Log temperature'}
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
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <form
      data-testid="capture-symptom-form"
      onSubmit={(e) => {
        e.preventDefault();
        setError('');
        mut.mutate();
      }}
      className="space-y-4"
    >
      <div>
        <label className="block text-xs text-gray-500 mb-1">Symptom</label>
        <select
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          className="w-full text-sm border-gray-200 rounded"
        >
          {SYMPTOM_SLUGS.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.label}
            </option>
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
    queryKey: ['today-v2', 'regimens', userId],
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
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      onSuccess();
    },
    onError: (e: Error) => setError(e.message),
  });

  if (isLoading) return <p className="text-xs text-gray-400">Loading regimens…</p>;

  if (!items.length) {
    return (
      <div data-testid="capture-medlog-empty" className="space-y-2 py-1">
        <p className="text-xs text-gray-600 font-medium">No active medication regimens</p>
        <p className="text-xs text-gray-400">
          Go to <span className="font-medium text-gray-600">Meds</span> in the navigation to create
          one.
        </p>
      </div>
    );
  }

  return (
    <form
      data-testid="capture-medlog-form"
      onSubmit={(e) => {
        e.preventDefault();
        setError('');
        mut.mutate();
      }}
      className="space-y-4"
    >
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

function ScaleSection() {
  const userId = getUserId();
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [msg, setMsg] = useState('');
  const [countdown, setCountdown] = useState<number | null>(null);

  const mut = useMutation({
    mutationFn: () => {
      setMsg('');
      abortRef.current = new AbortController();
      return scanScale(
        userId,
        abortRef.current.signal,
        loadScaleProfile(),
        loadScaleDevice()?.mac,
      );
    },
    onSuccess: (data) => {
      setMsg(data.message || 'Import complete');
      qc.invalidateQueries({ queryKey: ['today-v2'] });
      qc.invalidateQueries({ queryKey: ['scale-latest'] });
      qc.invalidateQueries({ queryKey: ['measurements'] });
      qc.invalidateQueries({ queryKey: ['freshness-scale'] });
    },
    onError: (e: Error) => {
      if (e.name !== 'AbortError') setMsg(e.message);
    },
    onSettled: () => setCountdown(null),
  });

  useEffect(() => {
    if (!mut.isPending) {
      setCountdown(null);
      return;
    }
    let remaining = SCAN_TIMEOUT_S;
    setCountdown(remaining);
    const id = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining <= 0 ? 0 : remaining);
      if (remaining <= 0) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [mut.isPending]);

  return (
    <div data-testid="capture-scale-section" className="space-y-4">
      <p className="text-xs text-gray-500">
        Power on your HC900 scale and keep it within Bluetooth range.
      </p>
      <button
        type="button"
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {mut.isPending ? `Scanning… ${countdown ?? SCAN_TIMEOUT_S}s` : 'Scan scale'}
      </button>
      {msg && (
        <p className={`text-xs font-mono ${mut.isSuccess ? 'text-green-600' : 'text-red-500'}`}>
          {msg}
        </p>
      )}
    </div>
  );
}

// ── Surface ───────────────────────────────────────────────────────────────

export default function CaptureSurface({
  initialSection = 'checkpoint',
  onClose,
}: {
  initialSection?: CaptureSection;
  onClose: () => void;
}) {
  const [section, setSection] = useState<CaptureSection>(initialSection);
  const [savedSection, setSavedSection] = useState<CaptureSection | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSaved = (s: CaptureSection) => {
    setSavedSection(s);
    setTimeout(() => setSavedSection(null), 1500);
  };

  const switchSection = (s: CaptureSection) => {
    setSavedSection(null);
    setSection(s);
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-white" data-testid="capture-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-12 border-b border-gray-100 shrink-0">
        <h2 className="text-sm font-semibold text-gray-900">Log</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close log"
          className="text-gray-400 hover:text-gray-700 text-lg leading-none"
        >
          &#x2715;
        </button>
      </div>

      {/* Section strip */}
      <div
        className="flex gap-1.5 px-4 py-3 border-b border-gray-100 overflow-x-auto shrink-0"
        data-testid="capture-section-strip"
      >
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => switchSection(s.id)}
            data-section={s.id}
            aria-pressed={section === s.id}
            className={`px-3 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
              section === s.id
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Form area */}
      <div className="flex-1 overflow-y-auto px-4 py-5 max-w-lg mx-auto w-full">
        {savedSection === section ? (
          <div className="text-center py-10" data-testid="capture-saved-feedback">
            <p className="text-green-600 font-medium text-sm">&#x2713; Saved</p>
          </div>
        ) : (
          <>
            {section === 'checkpoint' && (
              <CheckpointForm onSuccess={() => handleSaved('checkpoint')} />
            )}
            {section === 'measurement' && (
              <TemperatureForm onSuccess={() => handleSaved('measurement')} />
            )}
            {section === 'symptom' && (
              <SymptomForm onSuccess={() => handleSaved('symptom')} />
            )}
            {section === 'medlog' && (
              <MedLogForm onSuccess={() => handleSaved('medlog')} />
            )}
            {section === 'scale' && <ScaleSection />}
          </>
        )}
      </div>
    </div>
  );
}
