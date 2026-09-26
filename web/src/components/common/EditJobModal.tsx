import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  X,
  Pencil,
  Lock,
  AlertCircle,
  RefreshCw,
  Copy,
  ExternalLink,
} from 'lucide-react';
import { JobStateBadge } from './Badge';
import { jobsService, datasetsService, datasetBuildsService, systemService } from '../../api';
import {
  JobListItemData,
  JobDetailData,
  DatasetItemData,
  DatasetBuildListItemData,
  JobPatchRequest,
} from '../../types/api';

interface EditJobModalProps {
  job: JobListItemData | JobDetailData | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const EditJobModal: React.FC<EditJobModalProps> = ({
  job,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const navigate = useNavigate();

  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [epochs, setEpochs] = useState<number>(30);
  const [learningRate, setLearningRate] = useState<number>(0.01);
  const [seed, setSeed] = useState<number>(42);
  const [selectedModel, setSelectedModel] = useState<string>('resnet18_groupnorm');
  const [selectedBuildId, setSelectedBuildId] = useState<string>('');

  const [datasets, setDatasets] = useState<DatasetItemData[]>([]);
  const [builds, setBuilds] = useState<DatasetBuildListItemData[]>([]);
  const [supportedModels, setSupportedModels] = useState<string[]>(['resnet18_groupnorm', 'resnet18_standard']);

  const [loadingDetails, setLoadingDetails] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [cloning, setCloning] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize or fetch details when modal opens
  useEffect(() => {
    if (!isOpen || !job) return;

    setError(null);
    setDisplayName(job.display_name || '');
    setDescription((job as any).description || '');

    const loadJobDetails = async () => {
      try {
        setLoadingDetails(true);
        const promises: Promise<any>[] = [jobsService.getJob(job.job_id)];

        if (job.state === 'DRAFT') {
          promises.push(
            datasetsService.listDatasets({ limit: 50 }),
            datasetBuildsService.listBuilds({ limit: 100 }),
            systemService.getCapabilities()
          );
        }

        const results = await Promise.allSettled(promises);
        const jobRes = results[0];
        const dsRes = results[1];
        const buildsRes = results[2];
        const capRes = results[3];

        if (jobRes.status === 'fulfilled' && jobRes.value.data) {
          const fullJob = jobRes.value.data;
          setDisplayName(fullJob.display_name);
          setDescription(fullJob.description || '');

          if (fullJob.requested_contract) {
            setEpochs(fullJob.requested_contract.epochs ?? 30);
            setLearningRate(fullJob.requested_contract.learning_rate ?? 0.01);
            setSeed(fullJob.requested_contract.training_seed ?? 42);
            setSelectedModel(fullJob.requested_contract.model_id || 'resnet18_groupnorm');
            setSelectedBuildId(fullJob.requested_contract.dataset_build_id || '');
          }
        }

        if (dsRes && dsRes.status === 'fulfilled' && dsRes.value.data) {
          setDatasets(dsRes.value.data);
        }

        if (buildsRes && buildsRes.status === 'fulfilled' && buildsRes.value.data) {
          const readyBuilds = (buildsRes.value.data || []).filter((b: any) => b.state === 'READY');
          setBuilds(readyBuilds);
          if (!selectedBuildId && readyBuilds.length > 0) {
            setSelectedBuildId(readyBuilds[0].dataset_build_id);
          }
        }

        if (capRes && capRes.status === 'fulfilled' && capRes.value.data?.supported_models) {
          setSupportedModels(capRes.value.data.supported_models.map((m: any) => m.model_id));
        }
      } catch (err: any) {
        setError(err?.message || 'Failed to load job details');
      } finally {
        setLoadingDetails(false);
      }
    };

    loadJobDetails();
  }, [isOpen, job]);

  if (!isOpen || !job) return null;

  const isDraft = job.state === 'DRAFT';
  const isReady = job.state === 'READY';

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim()) {
      setError('Job name cannot be empty');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      let payload: JobPatchRequest;

      if (isDraft) {
        if (!selectedBuildId) {
          setError('Please select a valid dataset build');
          setSaving(false);
          return;
        }

        payload = {
          display_name: displayName.trim(),
          description: description.trim() || undefined,
          requested_contract: {
            dataset_build_id: selectedBuildId,
            model_id: selectedModel,
            epochs: Number(epochs),
            learning_rate: Number(learningRate),
            training_seed: Number(seed),
            training_strategy: 'strict_bsp',
          },
        };
      } else {
        // READY job: Only display_name and description can be updated (contract is frozen)
        payload = {
          display_name: displayName.trim(),
          description: description.trim() || undefined,
        };
      }

      await jobsService.patchJob(job.job_id, payload);
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to save job changes');
    } finally {
      setSaving(false);
    }
  };

  const handleClone = async () => {
    try {
      setCloning(true);
      const res = await jobsService.cloneJob(job.job_id);
      onClose();
      navigate(`/jobs/${res.data.job_id}`);
    } catch (err: any) {
      setError(err?.message || 'Failed to clone job');
    } finally {
      setCloning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 font-sans select-none">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-[#09090b]/80 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative bg-[#121214] border border-white/[0.08] rounded shadow-2xl max-w-lg w-full z-10 overflow-hidden animate-in zoom-in-95 duration-150 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-[#171719]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Pencil className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-[#f3f3f4]">
                  {isDraft ? 'Edit Draft Job' : 'Edit Job Metadata'}
                </h3>
                <JobStateBadge state={job.state} />
              </div>
              <p className="text-[11px] text-[#73737c]">
                ID: <span className="font-mono">{job.job_id}</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body Form */}
        <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          {error && (
            <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {/* Frozen contract notice for READY jobs */}
          {isReady && (
            <div className="p-3 rounded bg-amber-500/10 border border-amber-500/20 text-amber-200/90 space-y-1.5">
              <div className="flex items-center gap-1.5 font-medium text-amber-300">
                <Lock className="w-3.5 h-3.5" />
                <span>Training Contract Frozen</span>
              </div>
              <p className="text-[11px] text-amber-200/70">
                Job specification is frozen in <strong className="text-white">READY</strong> state. Model and dataset parameters are locked to guarantee contract hash immutability. You can edit the display name and description below, or clone to create a new editable draft.
              </p>
            </div>
          )}

          {loadingDetails && (
            <div className="py-6 flex items-center justify-center gap-2 text-[#73737c]">
              <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
              <span>Loading current job configuration...</span>
            </div>
          )}

          {/* Display Name */}
          <div className="space-y-1">
            <label className="block text-[11px] font-medium text-[#a1a1a8]">
              Job Name <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              required
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              placeholder="e.g. ResNet-18 StrictBSP CIFAR-10"
              className="w-full px-3 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500 transition-colors"
            />
          </div>

          {/* Description */}
          <div className="space-y-1">
            <label className="block text-[11px] font-medium text-[#a1a1a8]">
              Description
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional notes or experiment description..."
              className="w-full px-3 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500 transition-colors resize-none"
            />
          </div>

          {/* DRAFT Editable Contract Parameters */}
          {isDraft && (
            <div className="pt-2 border-t border-white/[0.06] space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold text-[#f3f3f4]">
                  Training Contract (DRAFT)
                </span>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    navigate(`/jobs/${job.job_id}/edit`);
                  }}
                  className="text-[11px] text-blue-400 hover:text-blue-300 inline-flex items-center gap-1 transition-colors"
                >
                  <span>Full wizard editor</span>
                  <ExternalLink className="w-3 h-3" />
                </button>
              </div>

              {/* Model & Dataset Row */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="block text-[11px] font-medium text-[#a1a1a8]">
                    Model
                  </label>
                  <select
                    value={selectedModel}
                    onChange={e => setSelectedModel(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500"
                  >
                    {supportedModels.map(m => (
                      <option key={m} value={m}>
                        {m.replace('model_', '').replace('_', ' ')}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="block text-[11px] font-medium text-[#a1a1a8]">
                    Dataset Build
                  </label>
                  <select
                    value={selectedBuildId}
                    onChange={e => setSelectedBuildId(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500 font-mono text-[11px]"
                  >
                    {builds.map(b => (
                      <option key={b.dataset_build_id} value={b.dataset_build_id}>
                        {b.dataset_id} ({b.dataset_build_id.slice(0, 8)}...)
                      </option>
                    ))}
                    {builds.length === 0 && selectedBuildId && (
                      <option value={selectedBuildId}>{selectedBuildId.slice(0, 8)}...</option>
                    )}
                  </select>
                </div>
              </div>

              {/* Epochs, Learning Rate, Seed */}
              <div className="grid grid-cols-3 gap-2.5 pt-1">
                <div className="space-y-1">
                  <label className="block text-[11px] font-medium text-[#a1a1a8]">
                    Epochs
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={epochs}
                    onChange={e => setEpochs(Math.max(1, parseInt(e.target.value) || 1))}
                    className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500"
                  />
                </div>

                <div className="space-y-1">
                  <label className="block text-[11px] font-medium text-[#a1a1a8]">
                    Learning Rate
                  </label>
                  <input
                    type="number"
                    step={0.0001}
                    min={0.00001}
                    value={learningRate}
                    onChange={e => setLearningRate(parseFloat(e.target.value) || 0.01)}
                    className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500"
                  />
                </div>

                <div className="space-y-1">
                  <label className="block text-[11px] font-medium text-[#a1a1a8]">
                    Seed
                  </label>
                  <input
                    type="number"
                    value={seed}
                    onChange={e => setSeed(parseInt(e.target.value) || 0)}
                    className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Locked parameters display for READY jobs */}
          {isReady && (
            <div className="pt-2 border-t border-white/[0.06] space-y-2">
              <span className="text-[11px] font-semibold text-[#73737c]">
                Locked Training Parameters
              </span>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="p-2 rounded bg-[#171719] border border-white/[0.05]">
                  <span className="text-[#73737c] block">Model</span>
                  <span className="text-[#f3f3f4] font-medium">{job.model_id || 'resnet18'}</span>
                </div>
                <div className="p-2 rounded bg-[#171719] border border-white/[0.05]">
                  <span className="text-[#73737c] block">Strategy</span>
                  <span className="text-[#f3f3f4] font-medium">{job.training_strategy || 'Strict BSP'}</span>
                </div>
              </div>
            </div>
          )}

          {/* Footer Actions */}
          <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between gap-2">
            <div>
              {isReady && (
                <button
                  type="button"
                  disabled={cloning || saving}
                  onClick={handleClone}
                  className="px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.08] transition-colors inline-flex items-center gap-1.5 text-xs"
                >
                  <Copy className="w-3.5 h-3.5 text-[#73737c]" />
                  <span>{cloning ? 'Cloning...' : 'Clone to Edit Spec'}</span>
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#a1a1a8] hover:text-[#f3f3f4] border border-white/[0.07] transition-colors text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || loadingDetails}
                className="px-3.5 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors text-xs inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                {saving ? (
                  <>
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <span>Save Changes</span>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
