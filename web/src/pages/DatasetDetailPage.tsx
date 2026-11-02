import React, { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ChevronRight,
  Play,
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

export const DatasetDetailPage: React.FC = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const navigate = useNavigate();

  const [datasetData, setDatasetData] = useState<DatasetDetailData | null>(null);
  const [buildsData, setBuildsData] = useState<DatasetBuildListItemData[]>([]);
  const [associatedJobs, setAssociatedJobs] = useState<JobListItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Tab navigation: Overview and Configurations (Preview tab removed per requirements)
  const [activeTab, setActiveTab] = useState<'overview' | 'configurations'>('overview');

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
        jobsService.listJobs({ limit: 100 }),
      ]);

      if (dsRes.status === 'fulfilled') {
        setDatasetData(dsRes.value.data);
        if (dsRes.value.data?.name && datasetId) {
          try {
            sessionStorage.setItem(`pbl4_ds_title_${datasetId}`, dsRes.value.data.name);
          } catch {}
        }
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
      setError(err?.message || 'Không thể tải thông tin tập dữ liệu');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasetDetail();
  }, [datasetId]);

  // Fallback dataset representation
  const dataset = {
    id: datasetData?.dataset_id || datasetId || '—',
    name: datasetData?.name || '—',
    task:
      datasetData?.task === 'image_classification' || datasetData?.task === 'Image classification'
        ? 'Phân loại ảnh'
        : datasetData?.task || 'Phân loại ảnh',
    totalSamples: buildsData.find(b => b.state === 'READY')?.sample_count,
    description: datasetData?.description || 'Chưa có mô tả chi tiết.',
    createdAt: datasetData?.created_at || '—',
  };

  // Map buildsData to local configuration format
  const configurations: DatasetBuild[] = buildsData.map(b => ({
    id: b.dataset_build_id,
    datasetId: b.dataset_id,
    datasetName: b.dataset_name || dataset.name,
    batchSize: b.batch_size ?? 0,
    state: b.state as any,
    shardCount: b.shard_count ?? 0,
    sampleCount: b.sample_count ?? 0,
    totalSamples: b.sample_count ?? 0,
    profile: b.profile || '—',
    createdAt: b.created_at || '—',
    shards: [],
  }));

  const readyConfigs = configurations.filter(b => b.state === 'READY');

  // Filter jobs that use this dataset or any of its builds
  const buildIds = new Set(buildsData.map(b => b.dataset_build_id));
  const jobsUsingDataset = associatedJobs.filter(job => {
    const bId = job.dataset_build_id || (job as any).datasetBuildId || (job as any).requestedContract?.datasetBuildId;
    if (bId && buildIds.has(bId)) return true;
    const dsId = (job as any).dataset_id || (job as any).datasetId || (job as any).requestedContract?.datasetId;
    if (dsId && dsId === datasetId) return true;
    return false;
  });

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
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
            Thử lại
          </button>
        </div>
      )}

      {/* Dataset Header */}
      <div className="space-y-3 pb-3 border-b border-white/[0.07]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              {dataset.name}
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Đang tải...
              </span>
            )}
          </div>

          <Link
            to={`/training/new?datasetId=${dataset.id}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors self-start sm:self-center shrink-0"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Dùng để huấn luyện</span>
          </Link>
        </div>

        {/* Tab Navigation: Tổng quan · Cấu hình phân vùng */}
        <div className="flex items-center gap-1.5 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'overview'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Tổng quan
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
            Cấu hình phân vùng ({configurations.length})
          </button>
        </div>
      </div>

      {/* ========================================================= */}
      {/* TAB 1: TỔNG QUAN                                          */}
      {/* ========================================================= */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          {/* Metadata row */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
            <div>
              <span className="text-[#73737c]">Tác vụ: </span>
              <span className="text-[#f3f3f4] font-medium">{dataset.task}</span>
            </div>
            <div>
              <span className="text-[#73737c]">Mẫu huấn luyện: </span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {dataset.totalSamples?.toLocaleString() ?? '—'}
              </span>
            </div>
            {dataset.description && dataset.description !== 'Chưa có mô tả chi tiết.' && (
              <div>
                <span className="text-[#73737c]">Mô tả: </span>
                <span className="text-[#a1a1a8]">{dataset.description}</span>
              </div>
            )}
          </div>

          {/* Associated Jobs using this dataset */}
          <div className="space-y-2 pt-1">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Nhiệm vụ sử dụng tập dữ liệu này ({jobsUsingDataset.length})
            </h2>
            {jobsUsingDataset.length > 0 ? (
              <div className="border border-white/[0.07] rounded bg-[#121214] divide-y divide-white/[0.04] overflow-hidden">
                {jobsUsingDataset.map(job => {
                  const jobId = job.job_id || (job as any).id;
                  const jobName = job.display_name || (job as any).name || 'Nhiệm vụ không tên';
                  const modelName = job.model_id || (job as any).modelId || (job as any).requestedContract?.modelArchitecture || '—';
                  const attemptCount = job.attempt_count ?? (job as any).attemptsCount ?? 0;

                  return (
                    <div
                      key={jobId}
                      onClick={() => navigate(`/jobs/${jobId}`)}
                      className="p-3 flex items-center justify-between text-xs hover:bg-[#171719] cursor-pointer transition-colors"
                    >
                      <div>
                        <span className="font-medium text-[#f3f3f4]">{jobName}</span>
                        <div className="text-[11px] text-[#73737c] mt-0.5">
                          {modelName} · {attemptCount} lần chạy
                        </div>
                      </div>
                      <ChevronRight className="w-3.5 h-3.5 text-[#73737c]" />
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 text-center text-xs text-[#73737c] border border-white/[0.07] rounded bg-[#121214]">
                Chưa có nhiệm vụ nào sử dụng tập dữ liệu này.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: CẤU HÌNH PHÂN VÙNG                                 */}
      {/* ========================================================= */}
      {activeTab === 'configurations' && (
        <div className="border border-white/[0.07] rounded bg-[#121214] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] text-[11px] bg-[#121214]">
                  <th className="py-2.5 px-3 font-medium">Cấu hình</th>
                  <th className="py-2.5 px-3 font-medium">Kích thước batch</th>
                  <th className="py-2.5 px-3 font-medium">Phân vùng dữ liệu</th>
                  <th className="py-2.5 px-3 font-medium">Số mẫu</th>
                  <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                  <th className="py-2.5 px-3 font-medium text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {configurations.map(config => {
                  const configName = getConfigurationDisplayName(config);
                  const isReady = config.state === 'READY';
                  const isDeprecated = config.state === 'DEPRECATED';
                  const partitionCount = config.shardCount ?? config.shards?.length ?? 0;
                  const totalSamples = config.totalSamples ?? config.sampleCount;

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
                        {config.batchSize} mẫu
                      </td>

                      {/* Data partitions */}
                      <td className="py-3 px-3 text-[#a1a1a8]">
                        {partitionCount} phân vùng
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
                            <span>Sẵn sàng</span>
                          </span>
                        ) : isDeprecated ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-[#73737c]">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#73737c]" />
                            <span>Không dùng nữa</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs text-rose-400">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                            <span>Thất bại</span>
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
                              Dùng để huấn luyện
                            </Link>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setSelectedConfig(config)}
                              className="px-2.5 py-1 text-xs text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] rounded transition-colors"
                            >
                              Chi tiết
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
