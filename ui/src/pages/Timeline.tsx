import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO, isToday } from 'date-fns';
import { getUserId } from '../config';
import {
  fetchIllnessSignal,
  fetchRecoveryStatus,
  fetchMeasurements,
  fetchCheckpoints,
  fetchSymptomLogs,
  todayISO,
} from '../api/client';
import SignalBadge from '../components/SignalBadge';

interface DayRow {
  date: string;
  hrv: number | null;
  illnessSignal: string | null;
  recoveryStatus: string | null;
  symptomCount: number;
  dominantSymptom: string | null;
  hasMorning: boolean;
  hasNight: boolean;
}

function offsetISO(base: Date, days: number): string {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function Timeline() {
  const userId = getUserId();
  const [weekOffset, setWeekOffset] = useState(0);

  // end = today shifted back by weekOffset weeks; start = end - 6 days
  const baseEnd = new Date(todayISO() + 'T12:00:00');
  baseEnd.setDate(baseEnd.getDate() - weekOffset * 7);
  const endISO = baseEnd.toISOString().slice(0, 10);
  const startISO = offsetISO(baseEnd, -6);

  const rangeLabel = weekOffset === 0
    ? 'Last 7 days'
    : `${format(parseISO(startISO), 'MMM d')} – ${format(parseISO(endISO), 'MMM d')}`;

  const illnessQ = useQuery({
    queryKey: ['illness', userId, startISO, endISO],
    queryFn: () => fetchIllnessSignal(userId, startISO, endISO),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const recoveryQ = useQuery({
    queryKey: ['recovery', userId, startISO, endISO],
    queryFn: () => fetchRecoveryStatus(userId, startISO, endISO),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const hrvQ = useQuery({
    queryKey: ['measurements', userId, 'hrv_rmssd', startISO, endISO],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 7),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const checkpointsQ = useQuery({
    queryKey: ['checkpoints', userId, startISO, endISO],
    queryFn: () => fetchCheckpoints(userId, startISO, endISO),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const symptomsQ = useQuery({
    queryKey: ['symptomLogs', userId],
    queryFn: () => fetchSymptomLogs(userId, 200),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const isLoading = illnessQ.isLoading || recoveryQ.isLoading || hrvQ.isLoading;

  // Build date range for the selected week, most recent first
  const dates: string[] = [];
  for (let i = 0; i < 7; i++) {
    dates.push(offsetISO(baseEnd, -i));
  }

  // Index data by date
  const illnessByDay = Object.fromEntries(
    (illnessQ.data?.days ?? []).map((d) => [d.day, d.signal_level])
  );
  const recoveryByDay = Object.fromEntries(
    (recoveryQ.data?.days ?? []).map((d) => [d.day, d.status])
  );
  const hrvByDay = Object.fromEntries(
    (hrvQ.data?.items ?? []).map((m) => [m.measured_at.slice(0, 10), m.value_num])
  );
  const checkpointsByDay: Record<string, { morning: boolean; night: boolean }> = {};
  for (const cp of checkpointsQ.data?.items ?? []) {
    if (!checkpointsByDay[cp.checkpoint_date]) {
      checkpointsByDay[cp.checkpoint_date] = { morning: false, night: false };
    }
    if (cp.checkpoint_type === 'morning') checkpointsByDay[cp.checkpoint_date].morning = true;
    if (cp.checkpoint_type === 'night') checkpointsByDay[cp.checkpoint_date].night = true;
  }
  const symptomsByDay: Record<string, { count: number; dominant: string | null }> = {};
  for (const sl of symptomsQ.data?.items ?? []) {
    const day = sl.started_at.slice(0, 10);
    if (day < startISO || day > endISO) continue;
    if (!symptomsByDay[day]) symptomsByDay[day] = { count: 0, dominant: null };
    symptomsByDay[day].count++;
    if (!symptomsByDay[day].dominant) symptomsByDay[day].dominant = sl.symptom_slug;
  }

  const rows: DayRow[] = dates.map((date) => ({
    date,
    hrv: hrvByDay[date] ?? null,
    illnessSignal: illnessByDay[date] ?? null,
    recoveryStatus: recoveryByDay[date] ?? null,
    symptomCount: symptomsByDay[date]?.count ?? 0,
    dominantSymptom: symptomsByDay[date]?.dominant ?? null,
    hasMorning: checkpointsByDay[date]?.morning ?? false,
    hasNight: checkpointsByDay[date]?.night ?? false,
  }));

  const formatDate = (iso: string) => {
    const d = parseISO(iso);
    return format(d, 'MMM d EEE');
  };

  const formatCheckin = (row: DayRow) => {
    if (row.hasMorning && row.hasNight) return '☀☾';
    if (row.hasMorning) return '☀';
    if (row.hasNight) return '☾';
    return '–';
  };

  if (isLoading) {
    return (
      <div className="space-y-2 animate-pulse">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="h-10 bg-gray-100 rounded" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-gray-400">{rangeLabel}</p>
        <div className="flex gap-1">
          <button
            onClick={() => setWeekOffset((w) => w + 1)}
            className="px-2 py-0.5 text-xs border border-gray-200 rounded hover:border-gray-400 text-gray-500 hover:text-gray-900 transition-colors"
          >
            ‹ Prev
          </button>
          <button
            onClick={() => setWeekOffset((w) => w - 1)}
            disabled={weekOffset === 0}
            className="px-2 py-0.5 text-xs border border-gray-200 rounded hover:border-gray-400 text-gray-500 hover:text-gray-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next ›
          </button>
        </div>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left px-3 py-2 text-gray-500 font-medium">Date</th>
              <th className="text-right px-3 py-2 text-gray-500 font-medium">HRV</th>
              <th className="px-3 py-2 text-gray-500 font-medium">Illness</th>
              <th className="px-3 py-2 text-gray-500 font-medium">Recovery</th>
              <th className="px-3 py-2 text-gray-500 font-medium">Symptoms</th>
              <th className="text-center px-3 py-2 text-gray-500 font-medium">Check-in</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.date}
                className={`border-b border-gray-50 last:border-0 ${
                  isToday(parseISO(row.date)) ? 'bg-blue-50/60' : i % 2 === 0 ? '' : 'bg-gray-50/40'
                }`}
              >
                <td className="px-3 py-2.5 font-mono text-gray-700">
                  {formatDate(row.date)}
                  {isToday(parseISO(row.date)) && (
                    <span className="ml-1 text-gray-400">·today</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-gray-700">
                  {row.hrv != null ? `${row.hrv} ms` : '–'}
                </td>
                <td className="px-3 py-2.5 text-center">
                  {row.illnessSignal ? (
                    <SignalBadge signal={row.illnessSignal} size="sm" />
                  ) : (
                    <span className="text-gray-300">–</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-center">
                  {row.recoveryStatus ? (
                    <SignalBadge signal={row.recoveryStatus} size="sm" />
                  ) : (
                    <span className="text-gray-300">–</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-center text-gray-600">
                  {row.symptomCount > 0 ? (
                    <span>
                      {row.symptomCount}
                      {row.dominantSymptom && (
                        <span className="text-gray-400 ml-1">{row.dominantSymptom.replace('_', ' ')}</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-gray-300">–</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-center font-mono text-gray-500">
                  {formatCheckin(row)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400 mt-2">– no reading for that day</p>
    </div>
  );
}
