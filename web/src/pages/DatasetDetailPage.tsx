import React, { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ChevronRight,
  ChevronLeft,
  Play,
  CheckCircle2,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { DatasetBuild } from '../types';
import {
  TrainingConfigurationDrawer,
  getConfigurationDisplayName,
  getConfigurationDescription,
} from '../components/drawers/TrainingConfigurationDrawer';
import { datasetsService, datasetBuildsService, jobsService } from '../api';
import { DatasetDetailData, DatasetBuildListItemData, JobListItemData } from '../types/api';

// Visual glyph representation for Kaggle-like dataset sample preview
const CifarGlyph: React.FC<{ label: string }> = ({ label }) => {
  switch (label) {
    case 'airplane':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.3c.4-.2.6-.6.5-1.1z" />
        </svg>
      );
    case 'automobile':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9C2.1 11.1 2 11.5 2 12v4c0 .6.4 1 1 1h2" />
          <circle cx="7" cy="17" r="2" />
          <path d="M9 17h6" />
          <circle cx="17" cy="17" r="2" />
        </svg>
      );
    case 'bird':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 7h.01" />
          <path d="M3.4 18H12a8 8 0 0 0 8-8V7a4 4 0 0 0-7.28-2.3L2 18" />
          <path d="m20 7 2 .5-2 .5" />
          <path d="M10 18v3" />
          <path d="M14 17.75V21" />
          <path d="M7 18a6 6 0 0 0 3.84-10.61" />
        </svg>
      );
    case 'cat':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5c.67 0 1.35.09 2 .26 1.78-2 5.03-2.84 6.42-2.26 1.4.58-.42 7-1.42 8.17.65 1.15 1 2.5 1 3.83 0 4.42-3.58 8-8 8s-8-3.58-8-8c0-1.33.35-2.68 1-3.83-1-1.17-2.82-7.59-1.42-8.17C4.97 2.42 8.22 3.26 10 5.26c.65-.17 1.33-.26 2-.26z" />
          <path d="m9 14 3-2 3 2" />
          <path d="M10 11.5a1 1 0 1 0 0-.01" />
          <path d="M14 11.5a1 1 0 1 0 0-.01" />
        </svg>
      );
    case 'deer':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M19 5c-1.5 0-2.8 1-3.4 2.4L13 14H7l-3 4" />
          <path d="M18 2v3" />
          <path d="M21 4l-2 1" />
          <path d="M15 3l1 2" />
          <path d="M7 14l-2 7" />
          <path d="M13 14l2 7" />
        </svg>
      );
    case 'dog':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 5.172C10 3.782 8.423 2.679 6.5 3c-2.823.47-4.113 6.006-4 7 .18 1.61 1.44 2.87 3 3v6a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-4" />
          <path d="M14 5.172C14 3.782 15.577 2.679 17.5 3c2.823.47 4.113 6.006 4 7-.18 1.61-1.44 2.87-3 3v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-4" />
          <circle cx="12" cy="14" r="3" />
          <path d="M11 13h.01" />
          <path d="M13 13h.01" />
        </svg>
      );
    case 'frog':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="6" cy="6" r="3" />
          <circle cx="18" cy="6" r="3" />
          <path d="M18 9a9 9 0 0 1-12 0" />
          <path d="M6 9a9 9 0 0 0 0 9h12a9 9 0 0 0 0-9" />
          <circle cx="6" cy="6" r="1" />
          <circle cx="18" cy="6" r="1" />
        </svg>
      );
    case 'horse':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 17c-2 0-3-1.5-3-3V6c0-1.7-1.3-3-3-3h-2.5C12 3 10.5 4.5 10.5 6v2L7 12H3l-1 3 2 1h3l3 5h2l-1-4 3-2 3 4h2v-2" />
        </svg>
      );
    case 'ship':
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1 .6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
          <path d="M19.38 20A11.6 11.6 0 0 0 21 14l-9-4-9 4c0 2.9.94 5.43 2.38 7" />
          <path d="M4 14V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v6" />
          <path d="M12 2v4" />
          <path d="M10 2h4" />
        </svg>
      );
    case 'truck':
    default:
      return (
        <svg viewBox="0 0 24 24" className="w-7 h-7 stroke-current" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" />
          <path d="M15 18H9" />
          <path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14" />
          <circle cx="17" cy="18" r="2" />
          <circle cx="7" cy="18" r="2" />
        </svg>
      );
  }
};

export const DatasetDetailPage: React.FC = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const navigate = useNavigate();

  const [datasetData, setDatasetData] = useState<DatasetDetailData | null>(null);
  const [buildsData, setBuildsData] = useState<DatasetBuildListItemData[]>([]);
  const [associatedJobs, setAssociatedJobs] = useState<JobListItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Three user-facing tabs
  const [activeTab, setActiveTab] = useState<'overview' | 'preview' | 'configurations'>('overview');

  // Preview tab state
  const [selectedClassFilter, setSelectedClassFilter] = useState<string>('all');
  const [previewPage, setPreviewPage] = useState<number>(1);

  // Configuration Detail Drawer state
  const [selectedConfig, setSelectedConfig] = useState<DatasetBuild | null>(null);

  const fetchDatasetDetail = async () => {
    if (!datasetId) return;
    try {
      setLoading(true);
      setError(null);
      const [dsRes, buildsRes, jobsRes] = await Promise.allSettled([
        datasetsService.getDataset(datasetId),
        datasetBuildsService.listBuilds({ dataset_id: datasetId }),
        jobsService.listJobs({ limit: 50 }),
      ]);

      if (dsRes.status === 'fulfilled') {
        setDatasetData(dsRes.value.data);
      } else {
        throw dsRes.reason;
      }

      if (buildsRes.status === 'fulfilled') {
        setBuildsData(buildsRes.value.data || []);
      }

      if (jobsRes.status === 'fulfilled') {
        setAssociatedJobs(jobsRes.value.data || []);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load dataset details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasetDetail();
  }, [datasetId]);

  // Fallback dataset representation
  const dataset = {
    id: datasetData?.dataset_id || datasetId || 'cifar10',
    name: datasetData?.name || 'CIFAR-10',
    task: datasetData?.task || 'Image classification',
    source: datasetData?.source_type || 'Built-in dataset',
    totalSamples: 50000,
    description:
      datasetData?.description ||
      'Standard computer vision benchmark dataset consisting of 60,000 32x32 color images in 10 classes, with 50,000 training samples and 10,000 test samples.',
    createdAt: datasetData?.created_at || '2026-08-18T10:00:00Z',
  };

  // Map buildsData to local configuration format
  const configurations: DatasetBuild[] = buildsData.map(b => ({
    id: b.dataset_build_id,
    datasetId: b.dataset_id,
    datasetName: b.dataset_name || dataset.name,
    batchSize: b.batch_size || 64,
    state: b.state as any,
    shardCount: b.shard_count || 3,
    sampleCount: b.sample_count || 50000,
    totalSamples: b.sample_count || 50000,
    profile: b.profile || 'standard-sharded-fp32',
    createdAt: b.created_at || '2026-09-08',
    shards: [],
  }));

  const readyConfigs = configurations.filter(b => b.state === 'READY');

  // CIFAR-10 classes for preview
  const classes = [
    'airplane',
    'automobile',
    'bird',
    'cat',
    'deer',
    'dog',
    'frog',
    'horse',
    'ship',
    'truck',
  ];

  // DESIGN_TARGET_NOT_PUBLIC_API: Kaggle-style simulated sample preview for UI demonstration
  const samplesPerPage = 12;
  const filteredClasses =
    selectedClassFilter === 'all'
      ? classes
      : [selectedClassFilter];

  const totalPoolSize = selectedClassFilter === 'all' ? 48 : 24;
  const totalPages = Math.ceil(totalPoolSize / samplesPerPage);

  const currentPreviewSamples = Array.from({ length: samplesPerPage }, (_, i) => {
    const globalIdx = (previewPage - 1) * samplesPerPage + i;
    const label = filteredClasses[globalIdx % filteredClasses.length];
    return {
      id: globalIdx + 1,
      label,
    };
  });

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-[#73737c]">
        <Link
          to="/datasets"
          className="hover:text-[#f3f3f4] flex items-center gap-1 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          <span>Datasets</span>
        </Link>
        <span>/</span>
        <span className="text-[#a1a1a8]">{dataset.name}</span>
      </div>

      {/* Error alert */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={fetchDatasetDetail}
            className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Dataset Header */}
      <div className="space-y-2 pb-3 border-b border-white/[0.07]">
        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold text-[#f3f3f4]">
                {dataset.name}
              </h1>
              {loading && (
                <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                  Loading...
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 text-xs text-[#73737c] mt-1 flex-wrap">
              <span>{dataset.task || 'Image classification'}</span>
              <span>·</span>
              <span>{dataset.source || 'Built-in dataset'}</span>
              <span>·</span>
              <span>{(dataset.totalSamples || 50000).toLocaleString()} training samples</span>
              <span>·</span>
              <span>{datasetData?.build_counts?.ready ?? readyConfigs.length} {readyConfigs.length === 1 ? 'configuration' : 'configurations'} ready</span>
            </div>
          </div>

          <Link
            to={`/training/new?datasetId=${dataset.id}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors self-start sm:self-center shrink-0"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Use for training</span>
          </Link>
        </div>

        {/* Tab Navigation: Overview · Preview · Training configurations */}
        <div className="flex items-center gap-1.5 pt-1 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'overview'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab('preview');
              setPreviewPage(1);
            }}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'preview'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Preview
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('configurations')}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'configurations'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Training configurations ({configurations.length})
          </button>
        </div>
      </div>

      {/* ========================================================= */}
      {/* TAB 1: OVERVIEW                                           */}
      {/* ========================================================= */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-4">
            {/* Primary Specification Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.07] bg-[#171719] rounded border border-white/[0.04]">
              <div className="p-3">
                <div className="text-[11px] text-[#73737c]">Task</div>
                <div className="text-xs font-medium text-[#f3f3f4] mt-0.5">
                  {dataset.task || 'Image classification'}
                </div>
              </div>

              <div className="p-3">
                <div className="text-[11px] text-[#73737c]">Source</div>
                <div className="text-xs font-medium text-[#f3f3f4] mt-0.5">
                  {dataset.source || 'Built-in dataset'}
                </div>
              </div>

              <div className="p-3">
                <div className="text-[11px] text-[#73737c]">Training samples</div>
                <div className="text-xs font-medium text-[#f3f3f4] mt-0.5">
                  {(dataset.totalSamples || 50000).toLocaleString()}
                </div>
              </div>

              <div className="p-3">
                <div className="text-[11px] text-[#73737c]">Configurations</div>
                <div className="text-xs font-medium text-[#f3f3f4] mt-0.5">
                  {readyConfigs.length} ready
                </div>
              </div>
            </div>

            {/* Description */}
            <div className="space-y-1.5 pt-1">
              <h2 className="text-xs font-semibold text-[#f3f3f4]">About this dataset</h2>
              <p className="text-xs text-[#a1a1a8] leading-relaxed max-w-3xl">
                {dataset.description ||
                  'Standard computer vision benchmark dataset consisting of 60,000 32x32 color images in 10 classes, with 50,000 training samples and 10,000 test samples.'}
              </p>
            </div>

            {/* Ready Configurations Action Summary */}
            <div className="pt-2 border-t border-white/[0.07] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="space-y-0.5 text-xs">
                <div className="text-[#f3f3f4] font-medium">
                  {readyConfigs.length} training configurations ready
                </div>
                <p className="text-[#73737c]">
                  Pre-partitioned and verified for immediate distributed execution.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab('configurations')}
                  className="px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] text-xs font-medium transition-colors"
                >
                  View configurations
                </button>
              </div>
            </div>

            {/* Associated Jobs / Run History on this dataset */}
            {associatedJobs.length > 0 && (
              <div className="pt-3 border-t border-white/[0.07] space-y-2">
                <h3 className="text-xs font-semibold text-[#f3f3f4]">
                  Trained models ({associatedJobs.length})
                </h3>
                <div className="divide-y divide-white/[0.04] border border-white/[0.04] rounded bg-[#171719]">
                  {associatedJobs.map(job => (
                    <div
                      key={job.id}
                      onClick={() => navigate(`/jobs/${job.id}`)}
                      className="p-3 flex items-center justify-between text-xs hover:bg-white/[0.02] cursor-pointer transition-colors"
                    >
                      <div>
                        <span className="font-medium text-[#f3f3f4]">{job.name}</span>
                        <div className="text-[11px] text-[#73737c] mt-0.5">
                          {job.requestedContract?.modelArchitecture || job.modelId || 'ResNet18'} · {job.attemptsCount} {job.attemptsCount === 1 ? 'attempt' : 'attempts'}
                        </div>
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-[#73737c]" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: PREVIEW (Kaggle-like clean sample grid)            */}
      {/* ========================================================= */}
      {activeTab === 'preview' && (
        <div className="space-y-4">
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-4">
            {/* Header with class filter */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h2 className="text-xs font-semibold text-[#f3f3f4]">
                  Dataset samples
                </h2>
                <p className="text-xs text-[#73737c] mt-0.5">
                  Visual preview across standard benchmark target classes
                </p>
              </div>

              {/* Pagination controls */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={previewPage <= 1}
                  onClick={() => setPreviewPage(p => Math.max(1, p - 1))}
                  className="px-2.5 py-1 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1"
                >
                  <ChevronLeft className="w-3 h-3" />
                  <span>Previous</span>
                </button>
                <span className="text-[11px] text-[#73737c] px-1">
                  Page {previewPage} of {totalPages}
                </span>
                <button
                  type="button"
                  disabled={previewPage >= totalPages}
                  onClick={() => setPreviewPage(p => p + 1)}
                  className="px-2.5 py-1 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1"
                >
                  <span>Next</span>
                  <ChevronRight className="w-3 h-3" />
                </button>
              </div>
            </div>

            {/* Class Filter Bar */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
              <button
                type="button"
                onClick={() => {
                  setSelectedClassFilter('all');
                  setPreviewPage(1);
                }}
                className={`px-2.5 py-1 rounded transition-colors whitespace-nowrap text-xs ${
                  selectedClassFilter === 'all'
                    ? 'bg-[#1f1f24] text-[#f3f3f4] font-medium border border-white/[0.1]'
                    : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-[#171719]'
                }`}
              >
                All classes
              </button>

              {classes.map(cls => (
                <button
                  key={cls}
                  type="button"
                  onClick={() => {
                    setSelectedClassFilter(cls);
                    setPreviewPage(1);
                  }}
                  className={`px-2.5 py-1 rounded capitalize transition-colors whitespace-nowrap text-xs ${
                    selectedClassFilter === cls
                      ? 'bg-[#1f1f24] text-[#f3f3f4] font-medium border border-white/[0.1]'
                      : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-[#171719]'
                  }`}
                >
                  {cls}
                </button>
              ))}
            </div>

            {/* Kaggle-like Image Grid: Clean thumbnails with class label */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 pt-1">
              {currentPreviewSamples.map(sample => (
                <div
                  key={`${sample.label}-${sample.id}`}
                  className="bg-[#171719] rounded border border-white/[0.05] p-2.5 flex flex-col items-center text-center space-y-2 group hover:border-white/[0.12] transition-colors"
                >
                  <div className="w-full aspect-square bg-[#0c0c0e] rounded flex items-center justify-center border border-white/[0.03] text-[#73737c] group-hover:text-[#f3f3f4] group-hover:bg-[#111114] transition-colors">
                    <CifarGlyph label={sample.label} />
                  </div>
                  <div className="w-full">
                    <div className="text-xs font-medium text-[#f3f3f4] capitalize truncate">
                      {sample.label}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Subtle Footnote: DESIGN_TARGET_NOT_PUBLIC_API marker */}
            <div className="pt-2 border-t border-white/[0.07] text-[11px] text-[#73737c]">
              Dataset sample preview · Visual exploration target (simulated client preview)
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: TRAINING CONFIGURATIONS                            */}
      {/* ========================================================= */}
      {activeTab === 'configurations' && (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xs font-semibold text-[#f3f3f4]">
                Training configurations ({configurations.length})
              </h2>
              <p className="text-xs text-[#73737c] mt-0.5">
                Pre-partitioned datasets ready for distributed model training
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] text-[11px] bg-[#121214]">
                  <th className="py-2.5 px-3 font-medium">Configuration</th>
                  <th className="py-2.5 px-3 font-medium">Batch size</th>
                  <th className="py-2.5 px-3 font-medium">Data partitions</th>
                  <th className="py-2.5 px-3 font-medium">Samples</th>
                  <th className="py-2.5 px-3 font-medium">Status</th>
                  <th className="py-2.5 px-3 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {configurations.map(config => {
                  const configName = getConfigurationDisplayName(config);
                  const isReady = config.state === 'READY';
                  const isDeprecated = config.state === 'DEPRECATED';
                  const partitionCount = config.shardCount || config.shards?.length || 3;
                  const totalSamples = config.totalSamples || config.sampleCount || 50000;

                  return (
                    <tr
                      key={config.id}
                      onClick={() => setSelectedConfig(config)}
                      className="hover:bg-[#171719] transition-colors cursor-pointer group"
                    >
                      {/* Configuration */}
                      <td className="py-3 px-3 font-medium text-[#f3f3f4]">
                        <div>{configName}</div>
                        <div className="text-[11px] text-[#73737c] font-normal mt-0.5">
                          {getConfigurationDescription(config)}
                        </div>
                      </td>

                      {/* Batch size */}
                      <td className="py-3 px-3 text-[#a1a1a8]">
                        {config.batchSize} samples
                      </td>

                      {/* Data partitions */}
                      <td className="py-3 px-3 text-[#a1a1a8]">
                        {partitionCount} partitions
                      </td>

                      {/* Samples */}
                      <td className="py-3 px-3 text-[#a1a1a8]">
                        {totalSamples.toLocaleString()}
                      </td>

                      {/* Status */}
                      <td className="py-3 px-3">
                        {isReady ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                            <span>Ready</span>
                          </span>
                        ) : isDeprecated ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-[#73737c]">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#73737c]" />
                            <span>Deprecated</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs text-rose-400">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                            <span>Failed</span>
                          </span>
                        )}
                      </td>

                      {/* Action */}
                      <td
                        className="py-3 px-3 text-right"
                        onClick={e => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-end gap-2">
                          {isReady ? (
                            <Link
                              to={`/training/new?datasetId=${dataset.id}&buildId=${config.id}`}
                              className="px-2.5 py-1 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                            >
                              Use for training
                            </Link>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setSelectedConfig(config)}
                              className="px-2.5 py-1 text-xs text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] rounded transition-colors"
                            >
                              Details
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Configuration Detail Drawer */}
      <TrainingConfigurationDrawer
        build={selectedConfig}
        dataset={dataset}
        isOpen={!!selectedConfig}
        onClose={() => setSelectedConfig(null)}
      />
    </div>
  );
};
