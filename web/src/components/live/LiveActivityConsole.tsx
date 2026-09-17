import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  ArrowDown,
  Check,
  AlertTriangle,
  X,
  Circle,
  Eye,
  Trash2,
  Play,
  Pause,
  Filter,
} from 'lucide-react';
import { DiagnosticEvent } from '../../types';
import {
  formatDiagnosticEvent,
  EventCategory,
  EventIconType,
} from '../../utils/eventFormatter';

interface LiveActivityConsoleProps {
  events: DiagnosticEvent[];
  onSelectEvent: (event: DiagnosticEvent) => void;
  isLive?: boolean;
}

export const LiveActivityConsole: React.FC<LiveActivityConsoleProps> = ({
  events,
  onSelectEvent,
  isLive = true,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<EventCategory>('all');
  const [autoFollow, setAutoFollow] = useState<boolean>(true);
  const [isScrolledUp, setIsScrolledUp] = useState<boolean>(false);
  const [clearedEventIds, setClearedEventIds] = useState<Set<string>>(new Set());

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isAutoScrollingRef = useRef<boolean>(false);

  // Filter events client-side
  const visibleEvents = useMemo(() => {
    return (events || []).filter(evt => {
      // Client-side clear filter
      if (clearedEventIds.has(evt.id)) {
        return false;
      }
      if (selectedCategory === 'all') return true;
      const formatted = formatDiagnosticEvent(evt);
      return formatted.category === selectedCategory;
    });
  }, [events, selectedCategory, clearedEventIds]);

  // Counts for filter pills
  const counts = useMemo(() => {
    let training = 0;
    let workers = 0;
    let checkpoints = 0;
    let warnings = 0;

    (events || []).forEach(evt => {
      const { category } = formatDiagnosticEvent(evt);
      if (category === 'training') training++;
      else if (category === 'workers') workers++;
      else if (category === 'checkpoints') checkpoints++;
      else if (category === 'warnings') warnings++;
    });

    return { all: (events || []).length, training, workers, checkpoints, warnings };
  }, [events]);

  // Handle scroll detection to toggle auto-follow
  const handleScroll = () => {
    if (isAutoScrollingRef.current) return;
    const el = scrollContainerRef.current;
    if (!el) return;

    // Check if user is scrolled up from the bottom
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 80) {
      setIsScrolledUp(true);
    } else {
      setIsScrolledUp(false);
    }
  };

  // Scroll to bottom when new events arrive IF autoFollow is enabled and user hasn't scrolled up
  useEffect(() => {
    if (!autoFollow || isScrolledUp) return;

    const el = scrollContainerRef.current;
    if (!el) return;

    isAutoScrollingRef.current = true;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth',
    });

    const timeout = setTimeout(() => {
      isAutoScrollingRef.current = false;
    }, 150);

    return () => clearTimeout(timeout);
  }, [(events || []).length, autoFollow, isScrolledUp]);

  const handleJumpToLatest = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    isAutoScrollingRef.current = true;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth',
    });
    setIsScrolledUp(false);
    setAutoFollow(true);
    setTimeout(() => {
      isAutoScrollingRef.current = false;
    }, 200);
  };

  const handleClearView = () => {
    setClearedEventIds(new Set((events || []).map(e => e.id)));
  };

  const handleRestoreView = () => {
    setClearedEventIds(new Set());
  };

  const renderStatusIcon = (type: EventIconType) => {
    switch (type) {
      case 'success':
        return <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />;
      case 'warning':
        return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />;
      case 'error':
        return <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />;
      case 'normal':
      default:
        return <span className="w-1.5 h-1.5 rounded-full bg-[#52525b] shrink-0" />;
    }
  };

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded flex flex-col overflow-hidden select-none font-sans">
      {/* Console Header */}
      <div className="bg-[#121214] border-b border-white/[0.07] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        {/* Left: Title & Live indicator & Filter chips */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-[#f3f3f4]">
              Live Activity
            </span>
            {isLive ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>Live</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-xs text-[#73737c]">
                <span>Paused</span>
              </span>
            )}
          </div>

          <div className="h-3.5 w-px bg-white/[0.07] hidden sm:block" />

          {/* Filter Tabs */}
          <div className="flex items-center gap-1 text-xs">
            {(['all', 'training', 'workers', 'checkpoints', 'warnings'] as EventCategory[]).map(cat => {
              const label =
                cat === 'all'
                  ? 'All'
                  : cat === 'training'
                  ? 'Training'
                  : cat === 'workers'
                  ? 'Workers'
                  : cat === 'checkpoints'
                  ? 'Checkpoints'
                  : 'Warnings';

              const count = counts[cat];
              const isSelected = selectedCategory === cat;

              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-2 py-0.5 rounded transition-colors text-xs inline-flex items-center gap-1 ${
                    isSelected
                      ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                      : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.02]'
                  }`}
                >
                  <span>{label}</span>
                  {count > 0 && (
                    <span className="text-[10px] text-[#73737c]">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Right: Controls (Auto-follow toggle, Clear view) */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAutoFollow(!autoFollow)}
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
              autoFollow
                ? 'text-[#f3f3f4] bg-[#171719] border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            <span>Auto-follow</span>
          </button>

          {clearedEventIds.size > 0 ? (
            <button
              type="button"
              onClick={handleRestoreView}
              className="text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors px-1.5 py-1"
            >
              Restore log
            </button>
          ) : (
            <button
              type="button"
              onClick={handleClearView}
              className="text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors px-1.5 py-1"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Main Console Output Area */}
      <div className="relative flex-1 min-h-[480px] max-h-[600px] flex flex-col bg-[#0b0b0c]">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-4 py-2 font-sans text-xs scroll-smooth divide-y divide-white/[0.03]"
        >
          {visibleEvents.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-center text-[#73737c] space-y-1">
              <p className="text-xs text-[#a1a1a8]">No activity in this view</p>
              <p className="text-xs text-[#73737c]">
                Waiting for incoming events or select another filter tab.
              </p>
            </div>
          ) : (
            // Chronological stream (oldest at top, newest at bottom)
            [...visibleEvents].reverse().map((evt, idx) => {
              const formatted = formatDiagnosticEvent(evt);
              const displayTime = evt.time && evt.time.length > 8 ? evt.time.slice(0, 8) : evt.time;

              return (
                <div
                  key={`${evt.id}-${evt.runtimeSeq ?? idx}`}
                  onClick={() => onSelectEvent(evt)}
                  className="group flex items-center justify-between py-1.5 px-1.5 -mx-1.5 rounded hover:bg-white/[0.02] transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {/* Timestamp: Small, muted */}
                    <span className="font-mono text-[11px] text-[#73737c] shrink-0 select-none">
                      {displayTime}
                    </span>

                    {/* Status Icon */}
                    {renderStatusIcon(formatted.iconType)}

                    {/* Human readable event sentence */}
                    <span className="text-[#f3f3f4] font-normal group-hover:text-white transition-colors truncate text-xs">
                      {formatted.humanText}
                    </span>

                    {/* Secondary metadata tag if available */}
                    {formatted.secondaryInfo && (
                      <span className="hidden sm:inline-block px-1.5 py-0.2 rounded bg-white/[0.03] text-[#73737c] text-[10px] font-mono shrink-0">
                        {formatted.secondaryInfo}
                      </span>
                    )}
                  </div>

                  {/* Right: Inspect indicator on hover */}
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[11px] text-blue-400 shrink-0 pl-2">
                    <Eye className="w-3 h-3" />
                    <span className="hidden md:inline">Inspect</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Floating Jump to Latest Button */}
        {isScrolledUp && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-20">
            <button
              type="button"
              onClick={handleJumpToLatest}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] text-xs font-normal border border-white/[0.07] transition-all cursor-pointer shadow-md"
            >
              <ArrowDown className="w-3 h-3" />
              <span>Jump to latest</span>
            </button>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="bg-[#121214] border-t border-white/[0.07] px-4 py-1.5 flex items-center justify-between text-xs text-[#73737c]">
        <span>WebSocket live event stream</span>
        <span>Click row to inspect payload</span>
      </div>
    </div>
  );
};
