import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { useApp } from '../../context/AppContext';
import { WorkerDetailDrawer } from '../drawers/WorkerDetailDrawer';
import { StepInspectorDrawer } from '../drawers/StepInspectorDrawer';
import { EventDetailDrawer } from '../drawers/EventDetailDrawer';
import { CheckpointDetailDrawer } from '../drawers/CheckpointDetailDrawer';
import { RawContractDrawer } from '../drawers/RawContractDrawer';

export const AppLayout: React.FC = () => {
  const {
    selectedWorker,
    setSelectedWorker,
    selectedStep,
    setSelectedStep,
    selectedEvent,
    setSelectedEvent,
    selectedCheckpoint,
    setSelectedCheckpoint,
    rawContractModalJob,
    setRawContractModalJob,
    resumeFromCheckpoint,
  } = useApp();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0b0b0c] text-[#f3f3f4] antialiased font-sans">
      {/* Fixed Left Sidebar */}
      <Sidebar />

      {/* Main Workspace Area */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden bg-[#0b0b0c]">
        <Topbar />

        {/* Scrollable Page Body */}
        <main className="flex-1 overflow-y-auto px-6 md:px-8 py-6">
          <div className="w-full space-y-6">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Global Slide-Over Inspector Drawers */}
      <WorkerDetailDrawer
        worker={selectedWorker}
        onClose={() => setSelectedWorker(null)}
      />
      <StepInspectorDrawer
        step={selectedStep}
        onClose={() => setSelectedStep(null)}
      />
      <EventDetailDrawer
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
      />
      <CheckpointDetailDrawer
        checkpoint={selectedCheckpoint}
        onClose={() => setSelectedCheckpoint(null)}
        onResume={resumeFromCheckpoint}
      />
      <RawContractDrawer
        job={rawContractModalJob}
        onClose={() => setRawContractModalJob(null)}
      />
    </div>
  );
};
