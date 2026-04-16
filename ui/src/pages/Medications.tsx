import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUserId } from '../config';
import {
  fetchAllRegimens,
  fetchMedicationDefinitions,
  createMedicationDefinition,
  createMedicationRegimen,
  createMedicationLog,
  deactivateRegimen,
  nowISO,
  todayISO,
} from '../api/client';
import type { MedicationRegimenResponse } from '../api/types';

const FREQUENCIES: { value: string; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'twice_daily', label: 'Twice daily' },
  { value: 'three_times_daily', label: '3x daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'as_needed', label: 'As needed' },
];

const DOSAGE_FORMS = ['tablet', 'capsule', 'liquid', 'injection', 'topical', 'inhaler'];

function formatFreq(f: string): string {
  return FREQUENCIES.find((x) => x.value === f)?.label ?? f;
}

function RegimenCard({
  regimen,
  onDeactivate,
  deactivating,
  onLog,
  logging,
  logFeedback,
}: {
  regimen: MedicationRegimenResponse;
  onDeactivate?: () => void;
  deactivating?: boolean;
  onLog?: () => void;
  logging?: boolean;
  logFeedback?: { ok: boolean; msg: string } | null;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-1">
      <div className="flex items-start justify-between">
        <div>
          <span className="text-sm font-medium text-gray-900">
            {regimen.medication_name ?? `Med #${regimen.medication_id}`}
          </span>
          <span className="ml-2 text-xs text-gray-400">
            {regimen.dosage_amount} {regimen.dosage_unit} &middot; {formatFreq(regimen.frequency)}
          </span>
        </div>
        {regimen.is_active && (
          <div className="flex items-center gap-2">
            {onLog && (
              <button
                onClick={onLog}
                disabled={logging}
                className="text-xs text-blue-400 hover:text-blue-600 disabled:opacity-50 transition-colors"
              >
                {logging ? '…' : 'Log'}
              </button>
            )}
            {logFeedback && (
              <span className={`text-xs ${logFeedback.ok ? 'text-green-500' : 'text-red-400'}`}>
                {logFeedback.ok ? '✓ Logged' : logFeedback.msg}
              </span>
            )}
            {onDeactivate && (
              <button
                onClick={onDeactivate}
                disabled={deactivating}
                className="text-xs text-red-400 hover:text-red-600 disabled:opacity-50 transition-colors"
              >
                {deactivating ? 'Stopping…' : 'Stop'}
              </button>
            )}
          </div>
        )}
      </div>
      <div className="text-xs text-gray-400">
        {regimen.started_at}
        {regimen.ended_at ? ` → ${regimen.ended_at}` : ' → ongoing'}
        {regimen.instructions && (
          <span className="ml-2 text-gray-400">· {regimen.instructions}</span>
        )}
      </div>
    </div>
  );
}

function RegimenForm({
  userId,
  onSuccess,
}: {
  userId: string;
  onSuccess: () => void;
}) {
  const qc = useQueryClient();

  const defsQ = useQuery({
    queryKey: ['medDefinitions'],
    queryFn: fetchMedicationDefinitions,
  });

  const [medId, setMedId] = useState<number | 'new'>('new');
  const [newName, setNewName] = useState('');
  const [newForm, setNewForm] = useState('tablet');
  const [newIngredient, setNewIngredient] = useState('');
  const [dosageAmount, setDosageAmount] = useState('');
  const [dosageUnit, setDosageUnit] = useState('mg');
  const [frequency, setFrequency] = useState('daily');
  const [startedAt, setStartedAt] = useState(todayISO());
  const [endedAt, setEndedAt] = useState('');
  const [instructions, setInstructions] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const defs = defsQ.data ?? [];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSaving(true);

    try {
      let medicationId = typeof medId === 'number' ? medId : 0;

      if (medId === 'new') {
        if (!newName.trim()) throw new Error('Medication name is required');
        const def = await createMedicationDefinition({
          name: newName.trim(),
          dosage_form: newForm || null,
          active_ingredient: newIngredient.trim() || null,
        });
        medicationId = def.id;
        qc.invalidateQueries({ queryKey: ['medDefinitions'] });
      }

      const amt = parseFloat(dosageAmount);
      if (isNaN(amt) || amt <= 0) throw new Error('Dosage amount must be positive');

      await createMedicationRegimen({
        user_id: userId,
        medication_id: medicationId,
        dosage_amount: amt,
        dosage_unit: dosageUnit.trim() || 'mg',
        frequency,
        started_at: startedAt,
        ended_at: endedAt || null,
        instructions: instructions.trim() || null,
      });

      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">New regimen</h3>

      {/* Medication selection */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Medication</label>
        <select
          value={medId}
          onChange={(e) => setMedId(e.target.value === 'new' ? 'new' : Number(e.target.value))}
          className="w-full text-sm border-gray-200 rounded"
        >
          <option value="new">+ Create new medication</option>
          {defs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}{d.dosage_form ? ` (${d.dosage_form})` : ''}
            </option>
          ))}
        </select>
      </div>

      {/* New medication fields */}
      {medId === 'new' && (
        <div className="space-y-2 pl-3 border-l-2 border-gray-100">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Omeprazole"
              className="w-full text-sm border-gray-200 rounded"
              required
            />
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Form</label>
              <select
                value={newForm}
                onChange={(e) => setNewForm(e.target.value)}
                className="w-full text-sm border-gray-200 rounded"
              >
                {DOSAGE_FORMS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Active ingredient</label>
              <input
                type="text"
                value={newIngredient}
                onChange={(e) => setNewIngredient(e.target.value)}
                placeholder="optional"
                className="w-full text-sm border-gray-200 rounded"
              />
            </div>
          </div>
        </div>
      )}

      {/* Dosage */}
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Dosage</label>
          <input
            type="number"
            value={dosageAmount}
            onChange={(e) => setDosageAmount(e.target.value)}
            step="0.01"
            min="0"
            placeholder="20"
            className="w-full text-sm border-gray-200 rounded"
            required
          />
        </div>
        <div className="w-24">
          <label className="block text-xs text-gray-500 mb-1">Unit</label>
          <input
            type="text"
            value={dosageUnit}
            onChange={(e) => setDosageUnit(e.target.value)}
            placeholder="mg"
            className="w-full text-sm border-gray-200 rounded"
          />
        </div>
      </div>

      {/* Frequency */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Frequency</label>
        <div className="flex flex-wrap gap-1">
          {FREQUENCIES.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setFrequency(f.value)}
              className={`px-2.5 py-1 text-xs rounded transition-colors ${
                frequency === f.value
                  ? 'bg-gray-900 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Dates */}
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Started</label>
          <input
            type="date"
            value={startedAt}
            onChange={(e) => setStartedAt(e.target.value)}
            className="w-full text-sm border-gray-200 rounded"
            required
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Ended (leave empty if ongoing)</label>
          <input
            type="date"
            value={endedAt}
            onChange={(e) => setEndedAt(e.target.value)}
            className="w-full text-sm border-gray-200 rounded"
          />
        </div>
      </div>

      {/* Instructions */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Instructions (optional)</label>
        <input
          type="text"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. take with food"
          className="w-full text-sm border-gray-200 rounded"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={saving}
        className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 disabled:opacity-50 transition-colors"
      >
        {saving ? 'Saving…' : endedAt ? 'Add past regimen' : 'Start regimen'}
      </button>
    </form>
  );
}

export default function Medications() {
  const userId = getUserId();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const [logFeedback, setLogFeedback] = useState<Record<string, { ok: boolean; msg: string }>>({});

  const regimensQ = useQuery({
    queryKey: ['allRegimens', userId],
    queryFn: () => fetchAllRegimens(userId),
    enabled: !!userId,
  });

  const deactivateMut = useMutation({
    mutationFn: (regimenId: string) => deactivateRegimen(regimenId, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['allRegimens'] });
      qc.invalidateQueries({ queryKey: ['activeRegimens'] });
      qc.invalidateQueries({ queryKey: ['adherence'] });
    },
  });

  const logMut = useMutation({
    mutationFn: (regimenId: string) => {
      const now = nowISO();
      return createMedicationLog({
        user_id: userId,
        regimen_id: regimenId,
        status: 'taken',
        scheduled_at: now,
        taken_at: now,
        recorded_at: now,
      });
    },
    onSuccess: (_data, regimenId) => {
      setLogFeedback((prev) => ({ ...prev, [regimenId]: { ok: true, msg: '' } }));
      setTimeout(() => setLogFeedback((prev) => { const n = { ...prev }; delete n[regimenId]; return n; }), 3000);
      qc.invalidateQueries({ queryKey: ['adherence'] });
      qc.invalidateQueries({ queryKey: ['medLogs'] });
    },
    onError: (e: Error, regimenId) => {
      setLogFeedback((prev) => ({ ...prev, [regimenId]: { ok: false, msg: e.message } }));
      setTimeout(() => setLogFeedback((prev) => { const n = { ...prev }; delete n[regimenId]; return n; }), 5000);
    },
  });

  const items = regimensQ.data?.items ?? [];
  const active = items.filter((r) => r.is_active);
  const past = items.filter((r) => !r.is_active);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">Medication Regimens</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs font-medium text-gray-500 hover:text-gray-900 border border-gray-200 rounded px-2 py-1 hover:border-gray-400 transition-colors"
        >
          {showForm ? 'Cancel' : '+ Add regimen'}
        </button>
      </div>

      {showForm && (
        <RegimenForm
          userId={userId}
          onSuccess={() => {
            setShowForm(false);
            qc.invalidateQueries({ queryKey: ['allRegimens'] });
            qc.invalidateQueries({ queryKey: ['activeRegimens'] });
          }}
        />
      )}

      {regimensQ.isLoading && <p className="text-xs text-gray-400">Loading…</p>}

      {!regimensQ.isLoading && active.length === 0 && !showForm && (
        <p className="text-xs text-gray-400 py-6 text-center">
          No active regimens. Add one to start tracking medication adherence.
        </p>
      )}

      <div className="space-y-2">
        {active.map((r) => (
          <RegimenCard
            key={r.id}
            regimen={r}
            onDeactivate={() => deactivateMut.mutate(r.id)}
            deactivating={deactivateMut.isPending}
            onLog={() => logMut.mutate(r.id)}
            logging={logMut.isPending && logMut.variables === r.id}
            logFeedback={logFeedback[r.id] ?? null}
          />
        ))}
      </div>

      {past.length > 0 && (
        <div>
          <button
            onClick={() => setShowPast(!showPast)}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {showPast ? '\u25be' : '\u25b8'} {past.length} past regimen{past.length !== 1 ? 's' : ''}
          </button>
          {showPast && (
            <div className="mt-2 space-y-2">
              {past.map((r) => (
                <RegimenCard key={r.id} regimen={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
