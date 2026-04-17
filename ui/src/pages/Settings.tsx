import { useEffect, useRef, useState } from 'react';
import { loadScaleProfile, saveScaleProfile, type ScaleProfile } from '../lib/scaleProfile';
import {
  loadScaleDevice,
  saveScaleDevice,
  clearScaleDevice,
  type ScaleDevice,
} from '../lib/scaleDevice';
import { discoverScales, type DiscoveredScale } from '../api/client';

export default function Settings() {
  const saved = loadScaleProfile();
  const [height, setHeight] = useState(saved.height_cm?.toString() ?? '');
  const [birthDate, setBirthDate] = useState(saved.birth_date ?? '');
  const [sex, setSex] = useState(saved.sex?.toString() ?? '');
  const [savedMsg, setSavedMsg] = useState(false);

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const profile: Partial<ScaleProfile> = {};
    if (height) profile.height_cm = Number(height);
    if (birthDate) profile.birth_date = birthDate;
    if (sex) profile.sex = Number(sex);
    saveScaleProfile(profile);
    setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2000);
  }

  return (
    <div className="space-y-10">
      <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Settings</h2>

      <section>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
          Scale Profile
        </h3>
        <p className="text-xs text-gray-400 mb-4">
          Used by the BLE scale scanner to compute body composition metrics.
        </p>
        <form onSubmit={handleSave} className="space-y-4 max-w-xs">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Height (cm)</label>
            <input
              type="number"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
              min={100}
              max={250}
              placeholder="178"
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-gray-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Birth date</label>
            <input
              type="date"
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-gray-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Sex</label>
            <select
              value={sex}
              onChange={(e) => setSex(e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-gray-400"
            >
              <option value="">— select —</option>
              <option value="1">Male</option>
              <option value="2">Female</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              className="px-4 py-1.5 text-xs font-medium bg-gray-900 text-white rounded hover:bg-gray-700 transition-colors"
            >
              Save
            </button>
            {savedMsg && <span className="text-xs text-green-500">Saved</span>}
          </div>
        </form>
      </section>

      <ScaleDeviceSection />
    </div>
  );
}

function ScaleDeviceSection() {
  const [paired, setPaired] = useState<ScaleDevice | null>(() => loadScaleDevice());
  const [discovering, setDiscovering] = useState(false);
  const [devices, setDevices] = useState<DiscoveredScale[]>([]);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function handleDiscover() {
    setError(null);
    setDevices([]);
    setDiscovering(true);
    abortRef.current = new AbortController();
    try {
      await discoverScales(
        (d) =>
          setDevices((prev) => (prev.some((x) => x.mac === d.mac) ? prev : [...prev, d])),
        abortRef.current.signal,
        15,
      );
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError((e as Error).message);
      }
    } finally {
      setDiscovering(false);
    }
  }

  function handleCancel() {
    abortRef.current?.abort();
    setDiscovering(false);
  }

  function handlePick(d: DiscoveredScale) {
    const dev: ScaleDevice = { mac: d.mac, name: d.name };
    saveScaleDevice(dev);
    setPaired(dev);
    setDevices([]);
  }

  function handleForget() {
    clearScaleDevice();
    setPaired(null);
  }

  const sorted = [...devices].sort((a, b) => b.rssi - a.rssi);

  return (
    <section>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
        Scale Device
      </h3>
      <p className="text-xs text-gray-400 mb-4">
        Pair your HC900 BLE scale once so the Scan button listens only for it.
      </p>

      {paired ? (
        <div className="max-w-md border border-gray-200 rounded p-3 flex items-center justify-between">
          <div>
            <div className="text-xs font-medium text-gray-700">{paired.name ?? 'HC900'}</div>
            <div className="text-[10px] text-gray-400 font-mono">{paired.mac}</div>
          </div>
          <button
            onClick={handleForget}
            className="px-3 py-1 text-[10px] text-gray-500 border border-gray-200 rounded hover:border-gray-400 hover:text-gray-900 transition-colors"
          >
            Forget
          </button>
        </div>
      ) : (
        <div className="max-w-md space-y-3">
          <div className="flex items-center gap-3">
            <button
              onClick={discovering ? handleCancel : handleDiscover}
              className="px-4 py-1.5 text-xs font-medium bg-gray-900 text-white rounded hover:bg-gray-700 transition-colors"
            >
              {discovering ? 'Cancel' : 'Pair scale'}
            </button>
            {discovering && (
              <span className="text-xs text-gray-500">
                Scanning… step on the scale so it advertises.
              </span>
            )}
          </div>
          {error && <div className="text-[10px] text-red-400">{error.slice(0, 140)}</div>}
          {(discovering || sorted.length > 0) && (
            <ul className="border border-gray-200 rounded divide-y divide-gray-100">
              {sorted.length === 0 && (
                <li className="px-3 py-2 text-[10px] text-gray-400">No devices yet…</li>
              )}
              {sorted.map((d) => (
                <li key={d.mac} className="px-3 py-2 flex items-center justify-between">
                  <div>
                    <div className="text-xs text-gray-700">{d.name ?? 'HC900'}</div>
                    <div className="text-[10px] text-gray-400 font-mono">
                      {d.mac} · {d.rssi} dBm
                    </div>
                  </div>
                  <button
                    onClick={() => handlePick(d)}
                    className="px-3 py-1 text-[10px] font-medium bg-gray-900 text-white rounded hover:bg-gray-700 transition-colors"
                  >
                    Select
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
