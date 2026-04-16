import { useState } from 'react';
import { loadScaleProfile, saveScaleProfile, type ScaleProfile } from '../lib/scaleProfile';

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
    <div className="space-y-6">
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
    </div>
  );
}
