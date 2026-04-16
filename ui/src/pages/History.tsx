import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { getUserId } from '../config';
import { fetchCheckpoints, fetchSymptomLogs, nDaysAgoISO, todayISO } from '../api/client';

function ScoreDot({ value, max = 10 }: { value: number | null; max?: number }) {
  if (value == null) return <span className="text-gray-300">–</span>;
  const pct = value / max;
  const cls = pct >= 0.7 ? 'text-green-600' : pct >= 0.4 ? 'text-amber-500' : 'text-red-400';
  return <span className={`font-mono ${cls}`}>{value}</span>;
}

function IntensityBadge({ value }: { value: number }) {
  const cls =
    value >= 7 ? 'bg-red-100 text-red-700' :
    value >= 4 ? 'bg-amber-100 text-amber-700' :
    'bg-gray-100 text-gray-600';
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono ${cls}`}>
      {value}
    </span>
  );
}

export default function History() {
  const userId = getUserId();
  const today = todayISO();
  const start = nDaysAgoISO(59);

  const checkpointsQ = useQuery({
    queryKey: ['history-checkpoints', userId, start, today],
    queryFn: () => fetchCheckpoints(userId, start, today),
    enabled: !!userId,
    staleTime: 2 * 60 * 1000,
  });

  const symptomsQ = useQuery({
    queryKey: ['history-symptoms', userId],
    queryFn: () => fetchSymptomLogs(userId, 200),
    enabled: !!userId,
    staleTime: 2 * 60 * 1000,
  });

  const checkpoints = [...(checkpointsQ.data?.items ?? [])]
    .sort((a, b) => b.checkpoint_at.localeCompare(a.checkpoint_at));

  const symptoms = [...(symptomsQ.data?.items ?? [])]
    .sort((a, b) => b.started_at.localeCompare(a.started_at));

  return (
    <div className="space-y-6">

      {/* Check-ins */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
          Check-ins <span className="font-normal normal-case tracking-normal">· last 60 days</span>
        </h2>
        {checkpointsQ.isLoading ? (
          <div className="space-y-1.5 animate-pulse">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-8 bg-gray-100 rounded" />
            ))}
          </div>
        ) : checkpoints.length === 0 ? (
          <p className="text-xs text-gray-400 py-4 text-center">No check-ins yet. Use + Input to log one.</p>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Date</th>
                  <th className="px-3 py-2 text-gray-500 font-medium">Type</th>
                  <th className="text-center px-2 py-2 text-gray-500 font-medium">Mood</th>
                  <th className="text-center px-2 py-2 text-gray-500 font-medium">Energy</th>
                  <th className="text-center px-2 py-2 text-gray-500 font-medium">Sleep</th>
                  <th className="text-center px-2 py-2 text-gray-500 font-medium">Body</th>
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {checkpoints.map((cp, i) => (
                  <tr
                    key={cp.id}
                    className={`border-b border-gray-50 last:border-0 ${i % 2 === 0 ? '' : 'bg-gray-50/40'}`}
                  >
                    <td className="px-3 py-2 font-mono text-gray-700 whitespace-nowrap">
                      {format(parseISO(cp.checkpoint_at), 'MMM d HH:mm')}
                    </td>
                    <td className="px-3 py-2 text-center text-gray-500 capitalize">
                      {cp.checkpoint_type}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <ScoreDot value={cp.mood} />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <ScoreDot value={cp.energy} />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <ScoreDot value={cp.sleep_quality} />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <ScoreDot value={cp.body_state_score} />
                    </td>
                    <td className="px-3 py-2 text-gray-400 truncate max-w-[120px]">
                      {cp.notes ?? '–'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Symptoms */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
          Symptoms <span className="font-normal normal-case tracking-normal">· last 200 entries</span>
        </h2>
        {symptomsQ.isLoading ? (
          <div className="space-y-1.5 animate-pulse">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-8 bg-gray-100 rounded" />
            ))}
          </div>
        ) : symptoms.length === 0 ? (
          <p className="text-xs text-gray-400 py-4 text-center">No symptoms logged yet.</p>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Date</th>
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Symptom</th>
                  <th className="text-center px-3 py-2 text-gray-500 font-medium">Intensity</th>
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {symptoms.map((sl, i) => (
                  <tr
                    key={sl.id}
                    className={`border-b border-gray-50 last:border-0 ${i % 2 === 0 ? '' : 'bg-gray-50/40'}`}
                  >
                    <td className="px-3 py-2 font-mono text-gray-700 whitespace-nowrap">
                      {format(parseISO(sl.started_at), 'MMM d HH:mm')}
                    </td>
                    <td className="px-3 py-2 text-gray-700 capitalize">
                      {sl.symptom_name ?? sl.symptom_slug?.replace(/_/g, ' ') ?? '–'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <IntensityBadge value={sl.intensity} />
                    </td>
                    <td className="px-3 py-2 text-gray-500 capitalize">
                      {sl.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
