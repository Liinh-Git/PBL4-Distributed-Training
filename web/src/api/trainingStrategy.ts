export type AsyncTrainingSettings = {
  units_per_contribution: number;
  staleness_threshold: number;
  reconnect_grace_seconds: number;
  assignment_timeout_seconds: number;
};

export const defaultAsyncSettings: AsyncTrainingSettings = {
  units_per_contribution: 1,
  staleness_threshold: 6,
  reconnect_grace_seconds: 60,
  assignment_timeout_seconds: 1800,
};

export const asyncSettingFields = [
  ['units_per_contribution', 'Work Unit mỗi lượt', 1, 4096],
  ['staleness_threshold', 'Độ trễ gradient tối đa (phiên bản)', 0, 1000000],
  ['reconnect_grace_seconds', 'Chờ khi mất hết Worker (giây)', 1, 3600],
  ['assignment_timeout_seconds', 'Thời gian tối đa mỗi lượt (giây)', 1, 86400],
] as const;

export function trainingStrategyFields(
  strategy: 'strict_bsp' | 'async_sgd',
  workload: 'equal' | 'dbs',
  units: number | undefined,
  settings: AsyncTrainingSettings,
) {
  if (strategy === 'async_sgd') {
    for (const [key, label, min, max] of asyncSettingFields) {
      if (!Number.isInteger(settings[key]) || settings[key] < min || settings[key] > max) {
        throw new Error(`${label}: nhập số nguyên từ ${min} đến ${max}.`);
      }
    }
  }
  return strategy === 'async_sgd'
    ? { training_strategy: strategy, workload_policy: 'equal' as const, async_training: settings }
    : { training_strategy: strategy, workload_policy: workload,
        ...(units === undefined ? {} : { work_units_per_step: units }) };
}
