const KEY = 'baseline_scale_profile';

export interface ScaleProfile {
  height_cm: number;
  birth_date: string;
  sex: number; // 1 = male, 2 = female
}

export function loadScaleProfile(): Partial<ScaleProfile> {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Partial<ScaleProfile>) : {};
  } catch {
    return {};
  }
}

export function saveScaleProfile(p: Partial<ScaleProfile>): void {
  localStorage.setItem(KEY, JSON.stringify(p));
}
