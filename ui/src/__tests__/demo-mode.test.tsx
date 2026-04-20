/**
 * B2 — Presentation Mode
 *
 * Tests:
 *  1. Normal mode: Nav shows all 6 view tabs
 *  2. Demo mode: Nav shows only Today, Progress, Record
 *  3. Demo mode: Timeline, Meds, Settings tabs absent
 *  4. Demo mode: + Log button still present
 *  5. Demo mode: priority drivers hidden from action items
 *  6. Normal mode: priority drivers visible in action items
 *  7. Demo mode: cause/affects debug line hidden in blocker items
 *  8. Normal mode: cause/affects line visible in blocker items
 *  9. isDemoMode() returns true when ?demo=true
 * 10. isDemoMode() returns false with no query param
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DemoContext } from '../context/DemoContext';
import Nav from '../components/Nav';
import TodayActionsList from '../features/today/components/TodayActionsList';
import TodayBlockersCard from '../features/today/components/TodayBlockersCard';
import { isDemoMode } from '../lib/demo';
import type { TodayActionVM } from '../features/today/types';
import type { TodayBlockerVM } from '../features/today/types';

// ── Fixtures ──────────────────────────────────────────────────────────────

function makeAction(overrides: Partial<TodayActionVM> = {}): TodayActionVM {
  return {
    id: 'action:check_in',
    kind: 'check_in',
    label: 'Morning check-in',
    reason: 'morning log pending',
    rank: 0,
    priorityDrivers: ['day_integrity', 'low_cost'],
    timeSensitive: false,
    estimatedCostSeconds: 30,
    ...overrides,
  };
}

function makeBlocker(overrides: Partial<TodayBlockerVM> = {}): TodayBlockerVM {
  return {
    id: 'blocker:weight:device_not_paired',
    kind: 'weight',
    affects: ['weight'],
    cause: 'device_not_paired',
    message: 'HC900 scale not paired',
    resolutionHint: 'Pair a scale in Settings',
    resolutionSurface: 'Settings',
    ...overrides,
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────

function renderNav(isDemo: boolean) {
  render(
    <DemoContext.Provider value={{ isDemo }}>
      <Nav view="today" onViewChange={vi.fn()} onOpenInput={vi.fn()} />
    </DemoContext.Provider>,
  );
}

function renderActions(isDemo: boolean, actions: TodayActionVM[]) {
  render(
    <DemoContext.Provider value={{ isDemo }}>
      <TodayActionsList actions={actions} onExecuteAction={vi.fn()} />
    </DemoContext.Provider>,
  );
}

function renderBlockers(isDemo: boolean, blockers: TodayBlockerVM[]) {
  render(
    <DemoContext.Provider value={{ isDemo }}>
      <TodayBlockersCard blockers={blockers} onResolveBlocker={vi.fn()} />
    </DemoContext.Provider>,
  );
}

// ── Nav tab visibility ────────────────────────────────────────────────────

describe('demo mode · Nav', () => {
  it('normal mode shows all 6 view tabs', () => {
    renderNav(false);
    expect(screen.getByRole('button', { name: /^today$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^progress$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^timeline$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^record$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^meds$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^settings$/i })).toBeInTheDocument();
  });

  it('demo mode shows only Today, Progress, Record tabs', () => {
    renderNav(true);
    expect(screen.getByRole('button', { name: /^today$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^progress$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^record$/i })).toBeInTheDocument();
  });

  it('demo mode hides Timeline, Meds, Settings tabs', () => {
    renderNav(true);
    expect(screen.queryByRole('button', { name: /^timeline$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^meds$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^settings$/i })).toBeNull();
  });

  it('demo mode keeps the + Log button', () => {
    renderNav(true);
    expect(screen.getByRole('button', { name: /\+ log/i })).toBeInTheDocument();
  });
});

// ── Chrome reduction: action priority drivers ─────────────────────────────

describe('demo mode · TodayActionsList', () => {
  it('demo mode hides priority drivers text, shows only reason', () => {
    renderActions(true, [makeAction()]);
    const item = screen.getByText('morning log pending');
    expect(item.textContent).not.toContain('day integrity');
    expect(item.textContent).not.toContain('low cost');
  });

  it('normal mode shows reason and priority drivers', () => {
    renderActions(false, [makeAction()]);
    // The combined text "morning log pending · day integrity · low cost" is in the paragraph
    const para = screen.getByText(/morning log pending/i);
    expect(para.textContent).toContain('day integrity');
  });

  it('demo mode still shows action label and rank', () => {
    renderActions(true, [makeAction()]);
    expect(screen.getByText('Morning check-in')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
  });
});

// ── Chrome reduction: blocker cause/affects line ──────────────────────────

describe('demo mode · TodayBlockersCard', () => {
  it('demo mode hides cause/affects debug line', () => {
    renderBlockers(true, [makeBlocker()]);
    expect(screen.queryByText(/cause:/i)).toBeNull();
    expect(screen.queryByText(/affects:/i)).toBeNull();
  });

  it('normal mode shows cause/affects debug line', () => {
    renderBlockers(false, [makeBlocker()]);
    expect(screen.getByText(/cause: device_not_paired/i)).toBeInTheDocument();
    expect(screen.getByText(/affects: weight/i)).toBeInTheDocument();
  });

  it('demo mode still shows blocker message and resolution hint', () => {
    renderBlockers(true, [makeBlocker()]);
    expect(screen.getByText('HC900 scale not paired')).toBeInTheDocument();
    expect(screen.getByText('Pair a scale in Settings')).toBeInTheDocument();
  });
});

// ── isDemoMode URL detection ──────────────────────────────────────────────

describe('isDemoMode()', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns true when URL has ?demo=true', () => {
    vi.stubGlobal('location', { search: '?demo=true' });
    expect(isDemoMode()).toBe(true);
  });

  it('returns false when URL has no demo param', () => {
    vi.stubGlobal('location', { search: '' });
    expect(isDemoMode()).toBe(false);
  });

  it('returns false when demo param has a different value', () => {
    vi.stubGlobal('location', { search: '?demo=false' });
    expect(isDemoMode()).toBe(false);
  });

  it('returns false when demo param is present but empty', () => {
    vi.stubGlobal('location', { search: '?demo=' });
    expect(isDemoMode()).toBe(false);
  });
});
