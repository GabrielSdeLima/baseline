import { createContext, useContext } from 'react';

export interface DemoContextValue {
  isDemo: boolean;
  /**
   * Placeholder for future demo dataset support.
   * When a curated demo dataset is introduced (Onda 4 B3+), this field
   * will carry the demo user ID or a dataMode discriminant so components
   * can switch data sources without structural changes.
   */
  // dataMode: 'live' | 'dataset';
}

export const DemoContext = createContext<DemoContextValue>({ isDemo: false });

export function useDemoMode(): DemoContextValue {
  return useContext(DemoContext);
}
