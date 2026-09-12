import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  ShieldCheck,
} from 'lucide-react';
import { useApp } from '../context/AppContext';

export const CreateJobPage: React.FC = () => {
  const { datasetBuilds, createJob } = useApp();
  const navigate = useNavigate();

  // Filter verified ready dataset builds
  const readyBuilds = (datasetBuilds || []).filter(b => b.state === 'READY');

  // Form states
  const [name, setName] = useState('ResNet18 CIFAR-10 Scaled Experiment');
  const [description, setDescription] = useState(
    'Distributed training job running ResNet18 under deterministic Strict BSP synchronization with 3 worker GPUs.'
  );
  const [modelArchitecture, setModelArchitecture] = useState('ResNet18');
  const [optimizer, setOptimizer] = useState('SGD');
  const [learningRate, setLearningRate] = useState(0.01);
  const [momentum, setMomentum] = useState(0.9);
  const [weightDecay, setWeightDecay] = useState(0.0005);
  const [batchSize, setBatchSize] = useState(64);
  const [targetEpochs, setTargetEpochs] = useState(20);
  const [expectedWorkers, setExpectedWorkers] = useState(3);
  const [checkpointIntervalSteps, setCheckpointIntervalSteps] = useState(500);
  const [datasetBuildId, setDatasetBuildId] = useState(
    readyBuilds[0]?.id || 'bld_cifar10_v2_ready'
  );

  const selectedBuild = readyBuilds.find(b => b.id === datasetBuildId);

  // Computed contract preview hash (mock deterministic representation)
  const computedHash = `0x9f4a${name?.length || 0}${batchSize}${expectedWorkers}${Math.floor(learningRate * 1000)}e8b39c01`;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newJob = createJob({
      name,
      description,
      state: 'READY',
      requestedContract: {
        modelArchitecture,
        optimizer,
        learningRate,
        momentum,
        weightDecay,
        batchSize,
        targetEpochs,
        trainingStrategy: 'STRICT_BSP',
        expectedWorkers,
        datasetBuildId,
        checkpointIntervalSteps,
      },
      resolvedContract: {
        modelArchitecture,
        hyperparameters: {
          learningRate,
          momentum,
          weightDecay,
          batchSize,
          epochs: targetEpochs,
          optimizer,
          seed: 42,
        },
        cluster: {
          expectedWorkers,
          synchronizationStrategy: 'STRICT_BSP',
          gradientAggregation: 'ALLREDUCE_SUM',
          parameterBroadcastMode: 'BROADCAST_ALL',
        },
        dataset: {
          datasetBuildId,
          partitionStrategy: selectedBuild?.partitionStrategy || selectedBuild?.profile || 'HASH_MODULO',
          totalSamples: selectedBuild?.totalSamples || selectedBuild?.sampleCount || 50000,
          manifestHash: selectedBuild?.manifestHash || selectedBuild?.datasetManifestHash || 'sha256_mock_hash',
        },
        checkpointing: {
          intervalSteps: checkpointIntervalSteps,
          keepLastN: 5,
          storageBackend: 'DISTRIBUTED_NFS',
        },
        contractHash: computedHash,
        resolvedAt: new Date().toISOString(),
      },
    });

    navigate(`/jobs/${newJob.id}`);
  };

  return (
    <div className="space-y-6 w-full pb-12 font-sans select-none">
      {/* Backlink */}
      <div className="flex items-center gap-2 text-xs text-[#73737c]">
        <Link to="/jobs" className="hover:text-[#f3f3f4] flex items-center gap-1 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Jobs</span>
        </Link>
      </div>

      <div>
        <h1 className="text-base font-semibold text-[#f3f3f4]">
          Create Training Job
        </h1>
        <p className="text-xs text-[#73737c] mt-0.5">
          Configure model parameters, distributed synchronization, and bind a verified dataset build.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* SECTION 1: Identity & Description */}
        <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
          <h2 className="text-xs font-semibold text-[#f3f3f4]">
            1. Job Details
          </h2>

          <div className="space-y-3 text-xs">
            <div>
              <label className="block text-[#73737c] mb-1">
                Job Name <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                required
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">
                Description
              </label>
              <textarea
                rows={2}
                value={description}
                onChange={e => setDescription(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#a1a1a8] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>
          </div>
        </div>

        {/* SECTION 2: Model Architecture & Hyperparameters */}
        <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
          <h2 className="text-xs font-semibold text-[#f3f3f4]">
            2. Model & Training Configuration
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div>
              <label className="block text-[#73737c] mb-1">
                Model Architecture
              </label>
              <select
                value={modelArchitecture}
                onChange={e => setModelArchitecture(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              >
                <option value="ResNet18">ResNet18</option>
                <option value="ResNet50">ResNet50</option>
                <option value="ViT-Small">ViT-Small</option>
              </select>
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">Optimizer</label>
              <select
                value={optimizer}
                onChange={e => setOptimizer(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              >
                <option value="SGD">SGD with Momentum</option>
                <option value="AdamW">AdamW</option>
              </select>
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">
                Learning Rate
              </label>
              <input
                type="number"
                step="0.001"
                min="0.00001"
                value={learningRate}
                onChange={e => setLearningRate(parseFloat(e.target.value))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">Momentum</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={momentum}
                onChange={e => setMomentum(parseFloat(e.target.value))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">
                Batch Size per Worker
              </label>
              <input
                type="number"
                step="8"
                min="8"
                max="512"
                value={batchSize}
                onChange={e => setBatchSize(parseInt(e.target.value, 10))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
              <span className="text-[11px] text-[#73737c] mt-1 block">
                Global synchronous batch: {batchSize * expectedWorkers} samples
              </span>
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">Target Epochs</label>
              <input
                type="number"
                min="1"
                max="200"
                value={targetEpochs}
                onChange={e => setTargetEpochs(parseInt(e.target.value, 10))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>
          </div>
        </div>

        {/* SECTION 3: Distributed Execution */}
        <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              3. Distributed Training & Synchronization
            </h2>
            <span className="text-[11px] text-[#73737c]">
              Strict BSP
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div>
              <label className="block text-[#73737c] mb-1">
                Synchronization Strategy
              </label>
              <input
                type="text"
                disabled
                value="Strict BSP (Bulk Synchronous Parallel)"
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.04] rounded text-xs text-[#73737c] cursor-not-allowed"
              />
              <span className="text-[11px] text-[#73737c] mt-1 block">
                Deterministic barrier synchronization across all active workers.
              </span>
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">
                Expected Workers
              </label>
              <input
                type="number"
                min="1"
                max="16"
                value={expectedWorkers}
                onChange={e => setExpectedWorkers(parseInt(e.target.value, 10))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>

            <div>
              <label className="block text-[#73737c] mb-1">
                Checkpoint Interval (Steps)
              </label>
              <input
                type="number"
                step="50"
                min="50"
                value={checkpointIntervalSteps}
                onChange={e => setCheckpointIntervalSteps(parseInt(e.target.value, 10))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              />
            </div>
          </div>
        </div>

        {/* SECTION 4: Verified Dataset Build Binding */}
        <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
          <h2 className="text-xs font-semibold text-[#f3f3f4]">
            4. Dataset
          </h2>

          <div className="space-y-3 text-xs">
            <div>
              <label className="block text-[#73737c] mb-1">
                Dataset Build <span className="text-rose-400">*</span>
              </label>
              <select
                value={datasetBuildId}
                onChange={e => setDatasetBuildId(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
              >
                {readyBuilds.map(b => (
                  <option key={b.id} value={b.id}>
                    {b.datasetName} — {b.id} ({((b.totalSamples ?? b.sampleCount ?? 0)).toLocaleString()} samples)
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Submit Actions */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <Link
            to="/jobs"
            className="px-3 py-1.5 text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] rounded transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            className="px-4 py-1.5 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5"
          >
            <Check className="w-3.5 h-3.5" />
            <span>Create Job</span>
          </button>
        </div>
      </form>
    </div>
  );
};
