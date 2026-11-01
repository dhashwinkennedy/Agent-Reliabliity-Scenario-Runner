import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Datasets from './pages/Datasets';
import Agents from './pages/Agents';
import Providers from './pages/Providers';
import Experiments from './pages/Experiments';
import Analytics from './pages/Analytics';

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 antialiased font-sans">
          {/* Persistent 6-Section Sidebar */}
          <Sidebar />

          {/* Main Content Area */}
          <div className="flex-1 flex flex-col min-w-0 bg-slate-950">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/datasets" element={<Datasets />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/providers" element={<Providers />} />
              <Route path="/experiments" element={<Experiments />} />
              <Route path="/experiments/:id" element={<Experiments />} />
              <Route path="/analytics" element={<Analytics />} />
              {/* Catch-all redirect to Dashboard */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
      </BrowserRouter>
    </ErrorBoundary>
  );
};

export default App;
