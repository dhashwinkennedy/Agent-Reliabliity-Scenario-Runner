import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onPageChange: (newOffset: number) => void;
  onLimitChange?: (newLimit: number) => void;
  limitOptions?: number[];
  isLoading?: boolean;
}

export const Pagination: React.FC<PaginationProps> = ({
  offset,
  limit,
  total,
  onPageChange,
  onLimitChange,
  limitOptions = [10, 25, 50, 100],
  isLoading = false,
}) => {
  if (total <= 0) {
    return null;
  }

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const startItem = offset + 1;
  const endItem = Math.min(offset + limit, total);

  const canPrev = offset > 0 && !isLoading;
  const canNext = offset + limit < total && !isLoading;

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-3 px-4 border-t border-slate-800 bg-slate-900/50 text-xs text-slate-400">
      <div className="flex items-center gap-2">
        <span>
          Showing <span className="font-semibold text-slate-200">{startItem}</span> to{' '}
          <span className="font-semibold text-slate-200">{endItem}</span> of{' '}
          <span className="font-semibold text-slate-200">{total}</span> records
        </span>
        {onLimitChange && (
          <div className="flex items-center gap-1.5 ml-4">
            <span>Per page:</span>
            <select
              value={limit}
              onChange={(e) => onLimitChange(Number(e.target.value))}
              disabled={isLoading}
              className="bg-slate-800 text-slate-200 rounded px-2 py-1 border border-slate-700 text-xs focus:ring-1 focus:ring-indigo-500 focus:outline-none"
            >
              {limitOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-slate-400 mr-2">
          Page <span className="font-medium text-slate-200">{currentPage}</span> of{' '}
          <span className="font-medium text-slate-200">{totalPages}</span>
        </span>
        <button
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          disabled={!canPrev}
          className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:hover:bg-slate-800 border border-slate-700 transition-colors"
          title="Previous Page"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => onPageChange(offset + limit)}
          disabled={!canNext}
          className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:hover:bg-slate-800 border border-slate-700 transition-colors"
          title="Next Page"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};

export default Pagination;
