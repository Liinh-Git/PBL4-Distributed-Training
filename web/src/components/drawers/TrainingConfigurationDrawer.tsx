import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Drawer } from '../common/Drawer';
import { DatasetBuild, Dataset } from '../../types';
import { DatasetBuildStateBadge } from '../common/Badge';
import { Play } from 'lucide-react';
import { formatDateOnly } from '../../utils/date';

export function getConfigurationDisplayName(build: DatasetBuild): string {
  if (build.state === 'DEPRECATED') return 'Cấu hình cũ';
  if (build.batchSize >= 128) return 'Batch lớn';
  if (build.batchSize === 64) return 'Tiêu chuẩn';
  return `Batch ${build.batchSize}`;
}

export function getConfigurationDescription(build: DatasetBuild): string {
  if (build.state === 'DEPRECATED') {
    return 'Cấu hình phân vùng cũ, được giữ lại cho việc đối sánh và kiểm tra lịch sử.';
  }
  if (build.batchSize >= 128) {
    return 'Tối ưu cho huấn luyện phân tán thông lượng cao với batch lớn cho mỗi worker.';
  }
  if (build.batchSize === 64) {
    return 'Cấu hình tiêu chuẩn cân bằng, khuyến nghị cho độ ổn định hội tụ thông thường.';
  }
  return `Cấu hình phân vùng tùy chỉnh với batch size ${build.batchSize}.`;
}

interface TrainingConfigurationDrawerProps {
  build: DatasetBuild | null;
  dataset: Dataset;
  isOpen: boolean;
  onClose: () => void;
}

export const TrainingConfigurationDrawer: React.FC<TrainingConfigurationDrawerProps> = ({
  build,
  dataset,
  isOpen,
  onClose,
}) => {
  const navigate = useNavigate();

  if (!build) return null;

  const configName = getConfigurationDisplayName(build);
  const isReady = build.state === 'READY';
  const partitionCount = build.shardCount ?? build.shards?.length ?? 0;
  const totalSamples = build.totalSamples ?? build.sampleCount;

  const handleUseForTraining = () => {
    navigate(`/training/new?datasetId=${dataset.id}&buildId=${build.id}`);
    onClose();
  };

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={configName}
      subtitle={`${dataset.name} · Cấu hình`}
      widthClass="max-w-md"
    >
      <div className="space-y-5 font-sans select-none text-xs">
        {/* Status header */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Trạng thái</span>
          <DatasetBuildStateBadge state={build.state} />
        </div>

        {/* Primary Operational Information */}
        <div className="space-y-3 pb-3 border-b border-white/[0.07]">
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Cấu hình</span>
            <span className="text-[#f3f3f4] font-medium">{configName}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Kích thước batch</span>
            <span className="text-[#f3f3f4] font-medium">{build.batchSize} mẫu</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Phân vùng dữ liệu</span>
            <span className="text-[#f3f3f4] font-medium">{partitionCount} phân vùng</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Tổng số mẫu</span>
            <span className="text-[#f3f3f4] font-medium">{totalSamples.toLocaleString()}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Ngày tạo</span>
            <span className="text-[#f3f3f4]">
              {formatDateOnly(build.createdAt)}
            </span>
          </div>
        </div>

        {/* Brief Human-readable description */}
        <div className="pb-3 border-b border-white/[0.07]">
          <p className="text-[#73737c] leading-relaxed">
            {getConfigurationDescription(build)}
          </p>
        </div>

        {/* Primary Action */}
        {isReady && (
          <div className="pt-1">
            <button
              type="button"
              onClick={handleUseForTraining}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Dùng để huấn luyện</span>
            </button>
          </div>
        )}
      </div>
    </Drawer>
  );
};
