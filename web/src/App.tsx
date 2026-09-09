import { BrowserRouter, Routes, Route } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import HomePage from './pages/HomePage'
import CurrentJobPage from './pages/CurrentJobPage'
import JobManagementPage from './pages/JobManagementPage'
import DatasetsPage from './pages/DatasetsPage'
import CheckpointsPage from './pages/CheckpointsPage'
import EventsPage from './pages/EventsPage'
import SystemPage from './pages/SystemPage'

function NotFound() {
  return (
    <div className="empty-state" style={{ marginTop: 60 }}>
      <div className="empty-state-icon">◌</div>
      <div className="empty-state-title">404 — Page not found</div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/current-job" element={<CurrentJobPage />} />
          <Route path="/attempts/:attemptId" element={<CurrentJobPage />} />
          <Route path="/jobs" element={<JobManagementPage />} />
          <Route path="/jobs/:jobId" element={<JobManagementPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/dataset-builds/:datasetBuildId" element={<DatasetsPage />} />
          <Route path="/checkpoints" element={<CheckpointsPage />} />
          <Route path="/checkpoints/:checkpointId" element={<CheckpointsPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
