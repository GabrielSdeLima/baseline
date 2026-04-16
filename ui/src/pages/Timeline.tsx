import { useQuery } from '@tanstack/react-query';
import { format, parseISO, isToday } from 'date-fns';
import { getUserId } from '../config';
import {
  fetchIllnessSignal,
  fetchRecoveryStatus,
  fetchMeasurements,
  fetchCheckpoints,
  fetchSymptomLogs,
  nDaysAgoISO,
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

export default function Timeline() {
  const userId = getUserId();
  const today = todayISO();
  const start = nDaysAgoISO(6); // 7 days inclusive

  const illnessQ = useQuery({
    queryKey: ['illness', userId, start, today],
    queryFn: () => fetchIllnessSignal(userId, start, today),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const recoveryQ = useQuery({
    queryKey: ['recovery', userId, start, today],
    queryFn: () => fetchRecoveryStatus(userId, start, today),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const hrvQ = useQuery({
    queryKey: ['measurements', userId, 'hrv_rmssd', 7],
    queryFn: () => fetchMeasurements(userId, 'hrv_rmssd', 7),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const checkpointsQ = useQuery({
    queryKey: ['checkpoints', userId, start, today],
    queryFn: () => fetchCheckpoints(userId, start, today),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const symptomsQ = useQuery({
    queryKey: ['symptomLogs', userId],
    queryFn: () => fetchSymptomLogs(userId, 50),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const isLoading = illnessQ.isLoading || recoveryQ.isLoading || hrvQ.isLoading;

  // Build date range for last 7 days, most recent first
  const dates: string[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    dates.push(d.toISOString().slice(0, 10));
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
      <p className="text-xs text-gray-400 mb-3">Last 7 days</p>
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
