import React from 'react';
import { Download } from 'lucide-react';
import { checkpointsService } from '../../api/checkpoints';

interface Props {
  checkpointId: string;
  className?: string;
}

export function ModelDownloadLink({ checkpointId, className = '' }: Props) {
  return (
    <a
      href={checkpointsService.modelDownloadUrl(checkpointId)}
      target="_blank"
      rel="noopener noreferrer"
      download
      title="Tải gói model ZIP và hướng dẫn nạp model"
      className={`inline-flex items-center justify-center gap-1.5 rounded border border-white/[0.1] px-3 py-1.5 text-xs text-[#f3f3f4] hover:bg-white/[0.07] ${className}`}
    >
      <Download className="w-3.5 h-3.5" />
      <span>Tải model</span>
    </a>
  );
}
