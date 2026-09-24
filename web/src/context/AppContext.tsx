import React, { createContext, useContext, useState } from 'react';
import {
  Job,
  DatasetBuild,
  TrainingStep,
  Checkpoint,
  DiagnosticEvent,
  WorkerSession,
} from '../types';

export interface AppContextType {
  // Transient UI Inspector Drawers State
  selectedWorker: WorkerSession | null;
  setSelectedWorker: (worker: WorkerSession | null) => void;
  selectedStep: TrainingStep | null;
  setSelectedStep: (step: TrainingStep | null) => void;
  selectedEvent: DiagnosticEvent | null;
  setSelectedEvent: (event: DiagnosticEvent | null) => void;
  selectedCheckpoint: Checkpoint | null;
  setSelectedCheckpoint: (checkpoint: Checkpoint | null) => void;
  selectedDatasetBuild: DatasetBuild | null;
  setSelectedDatasetBuild: (build: DatasetBuild | null) => void;
  rawContractModalJob: Job | null;
  setRawContractModalJob: (job: Job | null) => void;

  // Transient Diagnostics / Protocol indicators
  isRuntimeStale: boolean;
  setIsRuntimeStale: (stale: boolean) => void;
  hasEventHistoryGap: boolean;
  setHasEventHistoryGap: (gap: boolean) => void;
}

export const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Inspector drawer selections
  const [selectedWorker, setSelectedWorker] = useState<WorkerSession | null>(null);
  const [selectedStep, setSelectedStep] = useState<TrainingStep | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<DiagnosticEvent | null>(null);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null);
  const [selectedDatasetBuild, setSelectedDatasetBuild] = useState<DatasetBuild | null>(null);
  const [rawContractModalJob, setRawContractModalJob] = useState<Job | null>(null);

  // Transient diagnostic flags (driven by live attempt event stream)
  const [isRuntimeStale, setIsRuntimeStale] = useState<boolean>(false);
  const [hasEventHistoryGap, setHasEventHistoryGap] = useState<boolean>(false);

  return (
    <AppContext.Provider
      value={{
        selectedWorker,
        setSelectedWorker,
        selectedStep,
        setSelectedStep,
        selectedEvent,
        setSelectedEvent,
        selectedCheckpoint,
        setSelectedCheckpoint,
        selectedDatasetBuild,
        setSelectedDatasetBuild,
        rawContractModalJob,
        setRawContractModalJob,
        isRuntimeStale,
        setIsRuntimeStale,
        hasEventHistoryGap,
        setHasEventHistoryGap,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
