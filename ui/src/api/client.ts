import type {
  InsightSummary,
  PhysiologicalDeviationsResponse,
  IllnessSignalResponse,
  RecoveryStatusResponse,
  MedicationAdherenceResponse,
  MeasurementList,
  DailyCheckpointList,
  SymptomLogList,
  MedicationRegimenList,
  MedicationDefinitionResponse,
} from './types';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

export function nowISO(): string {
  return new Date().toISOString();
}

export function localToISO(localDatetime: string): string {
  return new Date(localDatetime).toISOString();
}

export function toDatetimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function nDaysAgoISO(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

// Insights
export const fetchSummary = (userId: string) =>
  apiFetch<InsightSummary>(`/insights/summary${qs({ user_id: userId })}`);

export const fetchDeviations = (userId: string, start: string, end: string) =>
  apiFetch<PhysiologicalDeviationsResponse>(
    `/insights/physiological-deviations${qs({ user_id: userId, start, end })}`
  );

export const fetchIllnessSignal = (userId: string, start: string, end: string) =>
  apiFetch<IllnessSignalResponse>(
    `/insights/illness-signal${qs({ user_id: userId, start, end })}`
  );

export const fetchRecoveryStatus = (userId: string, start: string, end: string) =>
  apiFetch<RecoveryStatusResponse>(
    `/insights/recovery-status${qs({ user_id: userId, start, end })}`
  );

export const fetchMedicationAdherence = (userId: string) =>
  apiFetch<MedicationAdherenceResponse>(
    `/insights/medication-adherence${qs({ user_id: userId })}`
  );

// Data
export const fetchMeasurements = (userId: string, slug: string, limit = 7) =>
  apiFetch<MeasurementList>(
    `/measurements/${qs({ user_id: userId, metric_type_slug: slug, limit })}`
  );

export const fetchCheckpoints = (userId: string, startDate: string, endDate: string) =>
  apiFetch<DailyCheckpointList>(
    `/checkpoints/${qs({ user_id: userId, start_date: startDate, end_date: endDate, limit: 14 })}`
  );

export const fetchSymptomLogs = (userId: string, limit = 50) =>
  apiFetch<SymptomLogList>(`/symptoms/logs${qs({ user_id: userId, limit })}`);

export const fetchActiveRegimens = (userId: string) =>
  apiFetch<MedicationRegimenList>(
    `/medications/regimens${qs({ user_id: userId, active_only: true })}`
  );

// Mutations
export const createCheckpoint = (body: object) =>
  apiFetch('/checkpoints/', { method: 'POST', body: JSON.stringify(body) });

export const createSymptomLog = (body: object) =>
  apiFetch('/symptoms/logs', { method: 'POST', body: JSON.stringify(body) });

export const createMedicationLog = (body: object) =>
  apiFetch('/medications/logs', { method: 'POST', body: JSON.stringify(body) });

export const createMeasurement = (body: object) =>
  apiFetch('/measurements/', { method: 'POST', body: JSON.stringify(body) });

// Medication definitions & regimen management
export const fetchMedicationDefinitions = () =>
  apiFetch<MedicationDefinitionResponse[]>('/medications/definitions');

export const createMedicationDefinition = (body: object) =>
  apiFetch<MedicationDefinitionResponse>('/medications/definitions', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const createMedicationRegimen = (body: object) =>
  apiFetch('/medications/regimens', { method: 'POST', body: JSON.stringify(body) });

export const fetchAllRegimens = (userId: string) =>
  apiFetch<MedicationRegimenList>(
    `/medications/regimens${qs({ user_id: userId })}`
  );

export const deactivateRegimen = (regimenId: string, userId: string) =>
  apiFetch(`/medications/regimens/${regimenId}/deactivate${qs({ user_id: userId })}`, {
    method: 'PATCH',
  });

// Integrations
export const scanScale = (userId: string) =>
  apiFetch<{ status: string; message: string }>(
    `/integrations/scale/scan${qs({ user_id: userId })}`,
    { method: 'POST' }
  );
