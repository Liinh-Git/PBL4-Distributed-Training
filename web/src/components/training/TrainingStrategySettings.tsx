import { useId } from 'react';
import { asyncSettingFields, type AsyncTrainingSettings } from '../../api/trainingStrategy';

export function TrainingStrategySettings({ strategy, settings, onStrategyChange, onSettingsChange }: {
  strategy: 'strict_bsp' | 'async_sgd';
  settings: AsyncTrainingSettings;
  onStrategyChange: (strategy: 'strict_bsp' | 'async_sgd') => void;
  onSettingsChange: (settings: AsyncTrainingSettings) => void;
}) {
  const id = useId();
  const inputStyle = 'mt-1 w-full rounded bg-[#171719] border border-white/10 p-2 focus-visible:outline-2 focus-visible:outline-blue-500';
  return <div className="space-y-3 text-xs">
    <label htmlFor={id} className="block">Chế độ huấn luyện</label>
    <select id={id} name="training_strategy" value={strategy} className={inputStyle}
      onChange={e => onStrategyChange(e.target.value as 'strict_bsp' | 'async_sgd')}>
      <option value="strict_bsp">Sync — StrictBSP</option>
      <option value="async_sgd">Async-SGD — có kết nối lại Worker</option>
    </select>
    {strategy === 'async_sgd' && <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {asyncSettingFields.map(([key, label, min, max]) => <label key={key} className="text-[#a1a1a8]">
        {label}<input name={key} type="number" required min={min} max={max} step={1}
          autoComplete="off" value={Number.isNaN(settings[key]) ? '' : settings[key]} className={inputStyle}
          onChange={e => onSettingsChange({ ...settings, [key]: e.target.valueAsNumber })} />
      </label>)}
    </div>}
  </div>;
}
