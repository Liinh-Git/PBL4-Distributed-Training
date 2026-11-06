import { useMemo } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { RuntimeEventItemData } from '../../types/api';
import { computeAsyncMetrics, type AsyncMetricPoint } from '../../utils/asyncMetrics';
import { computeEpochMetricsData, type EpochMetricData } from './LiveTrainingCharts';

type ChartPoint = Partial<AsyncMetricPoint> & { x: number; accuracy?: number | null };
interface Series { key: keyof ChartPoint; name: string; color: string }

function AsyncChart({ title, description, points, series, threshold, empty, unit, axis = 'Work Unit đã xử lý' }: {
  title: string;
  description: string;
  points: ChartPoint[];
  series: Series[];
  threshold?: number;
  empty: string;
  unit?: string;
  axis?: string;
}) {
  const hasData = points.some(point => series.some(item => point[item.key] != null));
  return <section aria-label={title} className="min-w-0 rounded border border-white/[0.07] bg-[#121214] p-4 space-y-3">
    <h3 className="text-sm font-semibold">{title}</h3>
    <p className="min-h-8 text-xs text-[#a1a1a8]">{description}</p>
    {hasData ? <div className="h-60 w-full min-w-0" role="img" aria-label={`${title}: ${points.length} kết quả gần nhất`}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <LineChart data={points} margin={{ top: 12, right: 18, bottom: 12, left: 0 }}>
          <CartesianGrid stroke="#27272a" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']} allowDecimals={false}
            tick={{ fill: '#a1a1a8', fontSize: 10 }} tickLine={false} axisLine={{ stroke: '#27272a' }} minTickGap={36} />
          <YAxis domain={[0, 'auto']} width={58} tick={{ fill: '#a1a1a8', fontSize: 10 }} tickLine={false} axisLine={false}
            tickFormatter={value => Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} />
          <Tooltip contentStyle={{ backgroundColor: '#171719', borderColor: '#3f3f46', color: '#f3f3f4', fontSize: 12 }}
            labelFormatter={label => `${axis}: ${Number(label).toLocaleString('vi-VN')}`}
            formatter={(value, name) => [value == null ? 'Chưa có số liệu' : `${Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ''}`, name]} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {threshold != null && <ReferenceLine y={threshold} stroke="#f59e0b" strokeDasharray="4 4" ifOverflow="extendDomain"
            label={{ value: `Ngưỡng ${threshold}`, fill: '#fbbf24', fontSize: 10, position: 'insideTopRight' }} />}
          {series.map(item => <Line key={item.key} dataKey={item.key} name={item.name} stroke={item.color}
            type="linear" strokeWidth={1.5} dot={points.length <= 40 ? { r: 2.5 } : false}
            activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div> : <div className="flex h-60 items-center justify-center rounded border border-dashed border-white/10 px-5 text-center text-xs text-[#a1a1a8]">{empty}</div>}
    <p className="text-[11px] text-[#a1a1a8]">Trục ngang: {axis}</p>
  </section>;
}

export function AsyncMetricsDashboard({ events, attemptId, stalenessThreshold, isStale, epochMetrics = [] }: {
  events: RuntimeEventItemData[];
  attemptId: string;
  stalenessThreshold?: number;
  isStale?: boolean;
  epochMetrics?: EpochMetricData[];
}) {
  const points = useMemo(() => computeAsyncMetrics(events, attemptId).map(point => ({ ...point, x: point.processedUnits })), [events, attemptId]);
  const epochs = useMemo(() => computeEpochMetricsData(epochMetrics).map(point => ({ x: point.epochNum, loss: point.loss, accuracy: point.accuracy })), [epochMetrics]);
  return <section aria-label="Biểu đồ Async-SGD" className="space-y-4">
    <h2 className="text-sm font-semibold">Kết quả theo epoch</h2>
    <p className="text-xs text-[#a1a1a8]">Loss và accuracy được chốt khi tất cả Work Unit của epoch đã xử lý xong, gồm cả lượt có gradient bị bỏ. Lịch sử epoch được tải từ PostgreSQL.</p>
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <AsyncChart title="Loss theo epoch" points={epochs} axis="Epoch" series={[{ key: 'loss', name: 'Loss epoch', color: '#60a5fa' }]}
        description="Trung bình loss có trọng số theo số mẫu, cùng cách tính với sync. Đây là loss trong quá trình huấn luyện."
        empty="Chưa có loss epoch đã chốt. Runtime phiên cũ không phát metrics epoch; phiên mới sẽ ghi nhận khi epoch hoàn tất." />
      <AsyncChart title="Accuracy theo epoch" points={epochs} axis="Epoch" unit="%" series={[{ key: 'accuracy', name: 'Accuracy epoch', color: '#34d399' }]}
        description="Tổng số dự đoán đúng chia cho tổng số mẫu của epoch, biểu diễn theo phần trăm."
        empty="Chưa có accuracy epoch đã chốt. Dữ liệu đo bị thiếu sẽ được giữ là chưa có số liệu." />
    </div>
    <div className="space-y-1">
      <h2 className="text-sm font-semibold">Diễn biến huấn luyện async</h2>
      <p className="text-xs text-[#a1a1a8]">{points.length.toLocaleString('vi-VN')} kết quả trong lịch sử gần nhất đã tải. Biểu đồ cập nhật sau mỗi lượt Worker gửi kết quả.</p>
      {isStale && <p role="status" className="text-xs text-amber-300">Đang hiển thị dữ liệu gần nhất; kết nối giám sát chưa được cập nhật.</p>}
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <AsyncChart title="Loss từng lượt" points={points} series={[{ key: 'loss', name: 'Loss', color: '#60a5fa' }]}
        description="Loss trên phần dữ liệu Worker vừa xử lý, gồm cả lượt có gradient bị bỏ. Đây là loss từng lượt, không phải trung bình epoch."
        empty="Chưa nhận được loss của lượt xử lý. Biểu đồ sẽ xuất hiện ngay khi có kết quả, không cần chờ hết epoch." />
      <AsyncChart title="Dữ liệu đã xử lý" points={points} series={[
        { key: 'appliedUnits', name: 'Dùng để cập nhật', color: '#34d399' },
        { key: 'droppedUnits', name: 'Bỏ do quá trễ', color: '#fbbf24' },
      ]} description="Số Work Unit tích lũy được dùng cập nhật model và bị bỏ do gradient quá trễ."
        empty="Chưa nhận được bộ đếm từ các lượt xử lý." unit="Work Unit" />
      <AsyncChart title="Độ trễ gradient" points={points} threshold={stalenessThreshold}
        series={[{ key: 'staleness', name: 'Độ trễ', color: '#fbbf24' }]}
        description="Số phiên bản model đã thay đổi từ lúc Worker nhận việc. Gradient vượt ngưỡng cấu hình sẽ bị bỏ."
        empty="Chưa có kết quả để đo độ trễ gradient." unit="phiên bản" />
      <AsyncChart title="Tốc độ xử lý" points={points} series={[{ key: 'samplesPerSecond', name: 'Tốc độ', color: '#22d3ee' }]}
        description="Mẫu/giây giữa hai kết quả liên tiếp, tính theo thời gian Runtime ghi sự kiện; gồm cả mẫu có gradient bị bỏ."
        empty="Cần ít nhất hai kết quả có thời gian và bộ đếm mẫu hợp lệ để tính tốc độ." unit="mẫu/giây" />
    </div>
    <p className="text-xs text-[#a1a1a8]">Các biểu đồ từng lượt bên trên bổ sung chẩn đoán cho kết quả tổng kết epoch.</p>
  </section>;
}
