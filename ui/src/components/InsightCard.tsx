interface Props {
  title: string;
  stability: 'stable' | 'experimental' | 'aggregate';
  method?: string;
  isLoading?: boolean;
  error?: Error | null;
  children: React.ReactNode;
}

export default function InsightCard({ title, stability, method, isLoading, error, children }: Props) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          {title}
        </h2>
        {stability === 'experimental' && (
          <span
            className="text-xs text-slate-400 font-mono cursor-help"
            title={method ? `heuristic: ${method}` : 'Experimental heuristic — V1'}
          >
            [exp]
          </span>
        )}
        {stability === 'aggregate' && (
          <span className="text-xs text-slate-400 font-mono" title="Aggregates stable + experimental insights">
            [agg]
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          <div className="h-4 bg-gray-100 rounded w-3/4" />
          <div className="h-4 bg-gray-100 rounded w-1/2" />
        </div>
      ) : error ? (
        <p className="text-xs text-red-500">Failed to load — {error.message}</p>
      ) : (
        children
      )}
    </div>
  );
}
