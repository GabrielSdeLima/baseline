# Baseline UI

React + TypeScript frontend for the Baseline personal health data platform.

## Development

```bash
npm install
npm run dev        # dev server on :5173 (proxies /api → :8000)
npm test           # vitest watch mode
npm run build      # production build → ../app/static/ui/
```

## Tech stack

- React 18 + TypeScript
- Vite
- Tailwind CSS
- TanStack Query (React Query v5)
- date-fns
- Vitest + @testing-library/react

## Pages

| Route | Component | Description |
|-------|-----------|-------------|
| Today | `pages/Today.tsx` | Insight summary + FreshnessBar |
| Timeline | `pages/Timeline.tsx` | 7-day rolling table with week nav |
| History | `pages/History.tsx` | Check-in + symptom log history |
| Meds | `pages/Medications.tsx` | Regimen management + quick log |

## Tests

```bash
npm test -- --run    # run once
npm test             # watch mode
```

61 tests across 5 files covering all pages and components.
