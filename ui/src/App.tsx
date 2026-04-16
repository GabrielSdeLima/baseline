import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { getUserId } from './config';
import Nav from './components/Nav';
import Today from './pages/Today';
import Timeline from './pages/Timeline';
import Medications from './pages/Medications';
import UserSetup from './pages/UserSetup';
import QuickInputModal from './components/QuickInputModal';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

type View = 'today' | 'timeline' | 'medications';

export default function App() {
  const userId = getUserId();

  if (!userId) {
    return <UserSetup />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
    </QueryClientProvider>
  );
}

function AppShell() {
  const [view, setView] = useState<View>('today');
  const [inputOpen, setInputOpen] = useState(false);

  return (
    <div className="min-h-screen bg-gray-50">
      <Nav view={view} onViewChange={setView} onOpenInput={() => setInputOpen(true)} />
      <main className="max-w-2xl mx-auto px-4 py-6">
        {view === 'today' && <Today />}
        {view === 'timeline' && <Timeline />}
        {view === 'medications' && <Medications />}
      </main>
      {inputOpen && <QuickInputModal onClose={() => setInputOpen(false)} />}
    </div>
  );
}
