import { useState } from 'react';
import { setUserId } from '../config';

export default function UserSetup() {
  const [id, setId] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = id.trim();
    if (!trimmed.match(/^[0-9a-f-]{36}$/i)) {
      setError('Enter a valid UUID (e.g. 01234567-89ab-cdef-0123-456789abcdef)');
      return;
    }
    setUserId(trimmed);
    window.location.reload();
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white border border-gray-200 rounded-lg p-8 w-full max-w-sm">
        <h1 className="font-mono text-lg font-semibold text-gray-900 mb-1">BASELINE</h1>
        <p className="text-xs text-gray-500 mb-6">Personal health data platform</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">User ID</label>
            <input
              type="text"
              value={id}
              onChange={(e) => setId(e.target.value)}
              placeholder="019d9334-bf04-77a1-..."
              className="w-full text-sm font-mono border-gray-200 rounded"
              autoFocus
            />
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            type="submit"
            className="w-full bg-gray-900 text-white text-sm py-2 rounded hover:bg-gray-700 transition-colors"
          >
            Connect
          </button>
        </form>
      </div>
    </div>
  );
}
