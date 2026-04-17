const KEY = 'baseline_scale_device';

export interface ScaleDevice {
  mac: string;
  name?: string;
}

export function loadScaleDevice(): ScaleDevice | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ScaleDevice) : null;
  } catch {
    return null;
  }
}

export function saveScaleDevice(d: ScaleDevice): void {
  localStorage.setItem(KEY, JSON.stringify(d));
}

export function clearScaleDevice(): void {
  localStorage.removeItem(KEY);
}
