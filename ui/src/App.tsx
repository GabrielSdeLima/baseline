import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { getUserId } from './config';
import Nav from './components/Nav';
import Today from './pages/Today';
import Progress from './pages/Progress';
import Timeline from './pages/Timeline';
import Record from './pages/Record';
import Medications from './pages/Medications';
import Settings from './pages/Settings';
import UserSetup from './pages/UserSetup';
import CaptureSurface, { type CaptureSection } from './components/CaptureSurface';
import { DemoContext } from './context/DemoContext';
import { isDemoMode } from './lib/demo';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

type View = 'today' | 'progress' | 'timeline' | 'record' | 'medications' | 'settings';

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
  const isDemo = isDemoMode();
  const [view, setView] = useState<View>('today');
  const [captureSection, setCaptureSection] = useState<CaptureSection | null>(null);

  const openCapture = (section?: CaptureSection) => setCaptureSection(section ?? 'checkpoint');
  const closeCapture = () => setCaptureSection(null);

  return (
    <DemoContext.Provider value={{ isDemo }}>
      <div className="min-h-screen bg-gray-50">
        <Nav view={view} onViewChange={setView} onOpenInput={() => openCapture()} />
        <main className="max-w-2xl mx-auto px-4 py-6">
          {view === 'today' && (
            <Today onOpenCapture={openCapture} onGoToSettings={() => setView('settings')} />
          )}
          {view === 'progress' && <Progress />}
          {view === 'timeline' && <Timeline />}
          {view === 'record' && <Record />}
          {view === 'medications' && <Medications />}
          {view === 'settings' && <Settings />}
        </main>
        {captureSection && <CaptureSurface initialSection={captureSection} onClose={closeCapture} />}
      </div>
    </DemoContext.Provider>
  );
}
