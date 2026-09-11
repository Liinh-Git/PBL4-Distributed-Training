import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import { AppLayout } from './components/layout/AppLayout';

import { OverviewPage } from './pages/OverviewPage';
import { LiveTrainingPage } from './pages/LiveTrainingPage';
import { JobsPage } from './pages/JobsPage';
import { JobDetailPage } from './pages/JobDetailPage';
import { NewTrainingFlowPage } from './pages/NewTrainingFlowPage';
import { DatasetsPage } from './pages/DatasetsPage';
import { DatasetDetailPage } from './pages/DatasetDetailPage';
import { DatasetBuildsPage } from './pages/DatasetBuildsPage';
import { DatasetBuildDetailPage } from './pages/DatasetBuildDetailPage';
import { CheckpointsPage } from './pages/CheckpointsPage';
import { EventsPage } from './pages/EventsPage';
import { SystemPage } from './pages/SystemPage';

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="live" element={<LiveTrainingPage />} />
            <Route path="training/new" element={<NewTrainingFlowPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="jobs/new" element={<NewTrainingFlowPage />} />
            <Route path="jobs/:jobId" element={<JobDetailPage />} />
            <Route path="datasets" element={<DatasetsPage />} />
            <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
            <Route path="datasets/:datasetId/builds/:buildId" element={<DatasetBuildDetailPage />} />
            <Route path="dataset-builds" element={<DatasetBuildsPage />} />
            <Route path="dataset-builds/:buildId" element={<DatasetBuildDetailPage />} />
            <Route path="checkpoints" element={<CheckpointsPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="system" element={<SystemPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
