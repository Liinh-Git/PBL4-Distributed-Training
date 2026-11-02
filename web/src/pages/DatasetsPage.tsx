import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, RefreshCw, AlertCircle } from 'lucide-react';
import { datasetsService, datasetBuildsService } from '../api';
import { DatasetItemData, DatasetBuildListItemData } from '../types/api';
import { formatDateOnly } from '../utils/date';

export const DatasetsPage: React.FC = () => {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<DatasetItemData[]>([]);
  const [builds, setBuilds] = useState<DatasetBuildListItemData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDatasets = async (cursor?: string | null, append = false) => {
    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const [datasetsRes, buildsRes] = await Promise.allSettled([
        datasetsService.listDatasets({ cursor, limit: 20 }),
        datasetBuildsService.listBuilds({ limit: 100 }),
      ]);

      if (datasetsRes.status === 'fulfilled') {
        const data = datasetsRes.value.data || [];
        setDatasets(prev => (append ? [...prev, ...data] : data));
        setNextCursor(datasetsRes.value.page?.next_cursor || null);
        try {
          data.forEach(d => {
            if (d.dataset_id && d.name) {
              sessionStorage.setItem(`pbl4_ds_title_${d.dataset_id}`, d.name);
            }
          });
        } catch {}
      } else {
        throw datasetsRes.reason;
      }

      if (buildsRes.status === 'fulfilled') {
        setBuilds(buildsRes.value.data || []);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load datasets from backend');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Tập dữ liệu
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Đang tải...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Các tập dữ liệu huấn luyện đã đăng ký cho các nhiệm vụ phân tán
          </p>
        </div>

        <button
          type="button"
          onClick={() => fetchDatasets()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#121214] border border-white/[0.07] hover:bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] text-xs transition-colors self-start sm:self-auto"
          title="Làm mới danh sách"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => fetchDatasets()}
            className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs transition-colors"
          >
            Thử lại
          </button>
        </div>
      )}

      {/* Dataset List */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] text-[11px] bg-[#121214]">
                <th className="py-2.5 px-3.5 font-medium">Tập dữ liệu</th>
                <th className="py-2.5 px-3.5 font-medium">Tác vụ</th>
                <th className="py-2.5 px-3.5 font-medium">Cấu hình</th>
                <th className="py-2.5 px-3.5 font-medium">Ngày tạo</th>
                <th className="py-2.5 px-3.5 font-medium text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && datasets.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#73737c]">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
                      <span>Đang tải danh mục tập dữ liệu...</span>
                    </div>
                  </td>
                </tr>
              ) : datasets.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#73737c]">
                    Không có tập dữ liệu nào được đăng ký.
                  </td>
                </tr>
              ) : (
                datasets.map(dataset => {
                  const datasetId = dataset.dataset_id;
                  const associatedBuilds = builds.filter(
                    b => b.dataset_id === datasetId || (dataset.name && b.dataset_name?.includes(dataset.name))
                  );
                  const configCount = dataset.build_counts?.total ?? associatedBuilds.length;

                  return (
                    <tr
                      key={datasetId}
                      onClick={() => navigate(`/datasets/${datasetId}`)}
                      className="hover:bg-[#171719] transition-colors cursor-pointer group"
                    >
                      <td className="py-3 px-3.5 font-medium text-[#f3f3f4]">
                        <div>{dataset.name}</div>
                        <div className="text-[11px] text-[#73737c] font-normal line-clamp-1 mt-0.5">
                          {dataset.description || 'Chưa có mô tả chi tiết.'}
                        </div>
                      </td>
                      <td className="py-3 px-3.5 text-[#a1a1a8]">
                        {dataset.task === 'image_classification' || dataset.task === 'Image classification'
                          ? 'Phân loại ảnh'
                          : dataset.task || 'Phân loại ảnh'}
                      </td>
                      <td className="py-3 px-3.5 text-[#a1a1a8]">
                        {configCount} cấu hình
                      </td>
                      <td className="py-3 px-3.5 text-[#73737c]">
                        {formatDateOnly(dataset.created_at)}
                      </td>
                      <td className="py-3 px-3.5 text-right text-[#73737c] group-hover:text-[#f3f3f4] transition-colors">
                        <ChevronRight className="w-3.5 h-3.5 inline-block" />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Cursor Pagination Load More */}
        {nextCursor && (
          <div className="p-3 border-t border-white/[0.07] flex justify-center">
            <button
              type="button"
              onClick={() => fetchDatasets(nextCursor, true)}
              disabled={loadingMore}
              className="px-4 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] transition-colors flex items-center gap-2"
            >
              {loadingMore && <RefreshCw className="w-3 h-3 animate-spin" />}
              <span>Tải thêm tập dữ liệu</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
