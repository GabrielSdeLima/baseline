/**
 * Visual + semantic validation for ScaleReadingCard.
 *
 * Each state below asserts the critical invariants (what MUST appear,
 * what MUST NOT leak) and prints a compact rendered view so the output
 * can be read as a textual screenshot during review.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScaleReadingCard from '../components/ScaleReadingCard';
import type { LatestScaleReading } from '../api/types';

function dump(label: string, html: string) {
  // Collapse whitespace and tags for a short snapshot printed to stdout.
  const text = html
    .replace(/<[^>]+>/g, '|')
    .replace(/\|+/g, ' | ')
    .replace(/\s+/g, ' ')
    .trim();
  // eslint-disable-next-line no-console
  console.log(`\n[${label}]\n  ${text}\n`);
}

function metric(
  slug: string,
  value: string,
  unit: string,
  is_derived: boolean,
) {
  return { slug, value, unit, is_derived };
}

// ── 1. full_reading V2 (glima shape — 18 metrics) ──────────────────────────────

const FULL_V2: LatestScaleReading = {
  status: 'full_reading',
  measured_at: '2026-04-16T22:42:24Z',
  raw_payload_id: '019d9875-ce63-73b0-9cc8-e6e047e486c0',
  decoder_version: 'hc900_ble_v2',
  has_impedance: true,
  metrics: {
    weight: metric('weight', '76.89', 'kg', false),
    impedance_adc: metric('impedance_adc', '526', 'adc', false),
    bmi: metric('bmi', '23.7', 'kg/m²', true),
    bmr: metric('bmr', '1713', 'kcal', true),
    body_fat_pct: metric('body_fat_pct', '21.5', '%', true),
    fat_free_mass_kg: metric('fat_free_mass_kg', '60.3', 'kg', true),
    fat_mass_kg: metric('fat_mass_kg', '16.5', 'kg', true),
    skeletal_muscle_mass_kg: metric('skeletal_muscle_mass_kg', '31.6', 'kg', true),
    skeletal_muscle_pct: metric('skeletal_muscle_pct', '41.1', '%', true),
    muscle_mass_kg: metric('muscle_mass_kg', '39.5', 'kg', true),
    muscle_pct: metric('muscle_pct', '51.4', '%', true),
    water_mass_kg: metric('water_mass_kg', '44.1', 'kg', true),
    water_pct: metric('water_pct', '57.4', '%', true),
    protein_mass_kg: metric('protein_mass_kg', '11.7', 'kg', true),
    protein_pct: metric('protein_pct', '15.2', '%', true),
    bone_mass_kg: metric('bone_mass_kg', '3.4', 'kg', true),
    ffmi: metric('ffmi', '18.6', 'kg/m²', true),
    fmi: metric('fmi', '5.1', 'kg/m²', true),
  },
};

// ── 2. full_reading V1 partial (Lucas shape — only weight + body_fat_pct) ──────

const FULL_V1_PARTIAL: LatestScaleReading = {
  status: 'full_reading',
  measured_at: '2026-04-15T07:30:00Z',
  raw_payload_id: '019d9241-3aae-79f0-ace0-0dc46f712efb',
  decoder_version: 'hc900_ble_v1',
  has_impedance: true,
  metrics: {
    weight: metric('weight', '75.84', 'kg', false),
    body_fat_pct: metric('body_fat_pct', '24.4', '%', false),
  },
};

// ── 3. weight_only (v2 parser with profile — emits bmi + bmr) ──────────────────

const WEIGHT_ONLY: LatestScaleReading = {
  status: 'weight_only',
  measured_at: '2026-04-16T19:00:00Z',
  raw_payload_id: '019d9999-aaaa-7bbb-9ccc-dddddddddddd',
  decoder_version: 'hc900_ble_v2',
  has_impedance: false,
  metrics: {
    weight: metric('weight', '76.40', 'kg', false),
    bmi: metric('bmi', '23.6', 'kg/m²', true),
    bmr: metric('bmr', '1709', 'kcal', true),
  },
};

// ── 4. never_measured (no HC900 ingestion yet) ─────────────────────────────────

const NEVER: LatestScaleReading = {
  status: 'never_measured',
  measured_at: null,
  raw_payload_id: null,
  decoder_version: null,
  has_impedance: false,
  metrics: {},
};


describe('ScaleReadingCard — visual + semantic validation', () => {
  describe('1. full_reading (V2, complete 18 metrics)', () => {
    it('shows weight, body-fat, muscle, water, BMI + impedance caveat', () => {
      const { container } = render(
        <ScaleReadingCard data={FULL_V2} isLoading={false} error={null} />
      );
      dump('full_reading V2', container.innerHTML);

      // Title
      expect(screen.getByText('Latest Scale Reading')).toBeInTheDocument();
      // Weight hero (2 decimals)
      expect(screen.getByText('76.89')).toBeInTheDocument();
      // Required body-comp fields
      expect(screen.getByText('Body fat')).toBeInTheDocument();
      expect(screen.getByText('21.5')).toBeInTheDocument();
      expect(screen.getByText('Muscle')).toBeInTheDocument();
      expect(screen.getByText('51.4')).toBeInTheDocument();
      expect(screen.getByText('Water')).toBeInTheDocument();
      expect(screen.getByText('57.4')).toBeInTheDocument();
      expect(screen.getByText('BMI')).toBeInTheDocument();
      expect(screen.getByText('23.7')).toBeInTheDocument();
      // Caveat + freshness
      expect(
        screen.getByText(/estimated from bioimpedance/i)
      ).toBeInTheDocument();
      expect(screen.getByText(/ago/)).toBeInTheDocument();
    });

    it('exposes decoder_version in the caveat tooltip', () => {
      const { container } = render(
        <ScaleReadingCard data={FULL_V2} isLoading={false} error={null} />
      );
      const caveat = container.querySelector('[title]');
      const title = caveat?.getAttribute('title') ?? '';
      expect(title).toMatch(/bioimpedance/i);
      expect(title).toContain('hc900_ble_v2');
    });

    it('does NOT show "body composition not captured" warning', () => {
      render(<ScaleReadingCard data={FULL_V2} isLoading={false} error={null} />);
      expect(
        screen.queryByText(/not captured/i)
      ).not.toBeInTheDocument();
    });
  });

  describe('2. full_reading V1 partial (graceful degradation)', () => {
    it('renders without crashing when only weight + body_fat_pct exist', () => {
      const { container } = render(
        <ScaleReadingCard data={FULL_V1_PARTIAL} isLoading={false} error={null} />
      );
      dump('full_reading V1 partial', container.innerHTML);

      // Available metrics render normally
      expect(screen.getByText('75.84')).toBeInTheDocument();
      expect(screen.getByText('24.4')).toBeInTheDocument(); // body fat
      // Missing slots degrade to em-dash, not crash
      const emDashes = screen.getAllByText('—');
      // BMI, Muscle, Water are absent in V1 partial → all 3 show "—"
      expect(emDashes.length).toBeGreaterThanOrEqual(3);
    });

    it('still shows the bioimpedance caveat (full_reading branch)', () => {
      render(
        <ScaleReadingCard data={FULL_V1_PARTIAL} isLoading={false} error={null} />
      );
      expect(
        screen.getByText(/estimated from bioimpedance/i)
      ).toBeInTheDocument();
    });
  });

  describe('3. weight_only (no impedance captured)', () => {
    it('shows weight + BMI/BMR + explicit "not captured" warning', () => {
      const { container } = render(
        <ScaleReadingCard data={WEIGHT_ONLY} isLoading={false} error={null} />
      );
      dump('weight_only', container.innerHTML);

      expect(screen.getByText('76.40')).toBeInTheDocument();
      expect(screen.getByText('BMI')).toBeInTheDocument();
      expect(screen.getByText('23.6')).toBeInTheDocument();
      expect(screen.getByText('BMR')).toBeInTheDocument();
      expect(screen.getByText('1709')).toBeInTheDocument();
      expect(
        screen.getByText(/body composition not captured/i)
      ).toBeInTheDocument();
    });

    it('does NOT leak body-comp fields from previous full readings', () => {
      render(
        <ScaleReadingCard data={WEIGHT_ONLY} isLoading={false} error={null} />
      );
      expect(screen.queryByText('Body fat')).not.toBeInTheDocument();
      expect(screen.queryByText('Muscle')).not.toBeInTheDocument();
      expect(screen.queryByText('Water')).not.toBeInTheDocument();
    });

    it('does NOT show the bioimpedance caveat (reserved for full readings)', () => {
      render(
        <ScaleReadingCard data={WEIGHT_ONLY} isLoading={false} error={null} />
      );
      expect(
        screen.queryByText(/estimated from bioimpedance/i)
      ).not.toBeInTheDocument();
    });
  });

  describe('4. never_measured (empty state)', () => {
    it('shows a neutral empty state with Scan hint — not an error', () => {
      const { container } = render(
        <ScaleReadingCard data={NEVER} isLoading={false} error={null} />
      );
      dump('never_measured', container.innerHTML);

      expect(screen.getByText(/no readings yet/i)).toBeInTheDocument();
      expect(screen.getByText(/Scan button/i)).toBeInTheDocument();
      expect(
        screen.queryByText(/Failed to load/i)
      ).not.toBeInTheDocument();
    });

    it('does NOT render a weight/body-comp grid', () => {
      render(<ScaleReadingCard data={NEVER} isLoading={false} error={null} />);
      expect(screen.queryByText('kg')).not.toBeInTheDocument();
      expect(screen.queryByText('Body fat')).not.toBeInTheDocument();
      expect(screen.queryByText('BMI')).not.toBeInTheDocument();
    });
  });
});
