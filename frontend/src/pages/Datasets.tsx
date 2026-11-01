import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Dataset, DatasetRecordItem } from '../types';
import Header from '../components/Header';
import StatusBadge from '../components/StatusBadge';
import Pagination from '../components/Pagination';
import Modal from '../components/Modal';
import JsonViewer from '../components/JsonViewer';
import ErrorAlert from '../components/ErrorAlert';
import {
  Upload,
  Database,
  Camera,
  Trash2,
  CheckCircle,
  AlertTriangle,
  RotateCw,
  FileText,
  Eye,
  Plus,
} from 'lucide-react';

export const Datasets: React.FC = () => {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(25);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Upload modal state
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [isUploading, setIsUploading] = useState(false);

  // Snapshot modal state
  const [snapshotDataset, setSnapshotDataset] = useState<Dataset | null>(null);
  const [snapshotName, setSnapshotName] = useState('');
  const [isCreatingSnapshot, setIsCreatingSnapshot] = useState(false);

  // Record inspector modal state
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null);
  const [records, setRecords] = useState<DatasetRecordItem[]>([]);
  const [recordsOffset, setRecordsOffset] = useState(0);
  const [recordsLimit, setRecordsLimit] = useState(10);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [isLoadingRecords, setIsLoadingRecords] = useState(false);

  // Load datasets list
  const loadDatasets = useCallback(async (currentOffset = offset, currentLimit = limit) => {
    setIsLoading(true);
    setActionError(null);
    try {
      const res = await api.listDatasets({ offset: currentOffset, limit: currentLimit });
      setDatasets(res.items || []);
      setTotal(res.total || 0);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to load datasets');
    } finally {
      setIsLoading(false);
    }
  }, [offset, limit]);

  useEffect(() => {
    loadDatasets(offset, limit);
  }, [loadDatasets, offset, limit]);

  // Load records for inspection
  const loadRecords = async (datasetId: string, currentOffset = 0, currentLimit = 10) => {
    setIsLoadingRecords(true);
    try {
      const res = await api.getDatasetRecords(datasetId, {
        offset: currentOffset,
        limit: currentLimit,
      });
      setRecords(res.items || []);
      setRecordsTotal(res.total || 0);
      setRecordsOffset(currentOffset);
      setRecordsLimit(currentLimit);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to load dataset records');
    } finally {
      setIsLoadingRecords(false);
    }
  };

  const handleOpenRecords = (ds: Dataset) => {
    setSelectedDataset(ds);
    loadRecords(ds.id, 0, 10);
  };

  // Revalidate dataset
  const handleRevalidate = async (datasetId: string) => {
    setActionError(null);
    setActionSuccess(null);
    try {
      await api.validateDataset(datasetId);
      setActionSuccess('Dataset re-validated successfully.');
      loadDatasets();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Revalidation failed');
    }
  };

  // Create snapshot
  const handleCreateSnapshot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!snapshotDataset) return;
    setIsCreatingSnapshot(true);
    setActionError(null);
    try {
      await api.createSnapshot(snapshotDataset.id, snapshotName || undefined);
      setActionSuccess(`Immutable snapshot created for ${snapshotDataset.display_name}`);
      setSnapshotDataset(null);
      setSnapshotName('');
      loadDatasets();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Snapshot creation failed');
    } finally {
      setIsCreatingSnapshot(false);
    }
  };

  // Delete dataset
  const handleDelete = async (dataset: Dataset) => {
    if (!window.confirm(`Are you sure you want to delete dataset "${dataset.display_name}"?`)) {
      return;
    }
    setActionError(null);
    setActionSuccess(null);
    try {
      await api.deleteDataset(dataset.id);
      setActionSuccess(`Dataset "${dataset.display_name}" deleted.`);
      loadDatasets();
    } catch (err: unknown) {
      // Honestly display backend errors (e.g., if snapshots exist)
      setActionError(err instanceof Error ? err.message : 'Failed to delete dataset');
    }
  };

  // Upload dataset
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) return;
    setIsUploading(true);
    setActionError(null);
    try {
      const res = await api.uploadDataset(uploadFile, displayName || undefined);
      setActionSuccess(`Uploaded dataset "${res.display_name}" (${res.record_count} records)`);
      setIsUploadOpen(false);
      setUploadFile(null);
      setDisplayName('');
      loadDatasets();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title="Datasets Management"
        subtitle="Upload JSON/JSONL datasets, inspect records, and produce immutable snapshots"
        onRefresh={() => loadDatasets(offset, limit)}
        isRefreshing={isLoading}
        actions={
          <button
            onClick={() => setIsUploadOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
          >
            <Upload className="h-4 w-4" />
            <span>Upload Dataset</span>
          </button>
        }
      />

      <main className="p-8 space-y-6 max-w-7xl mx-auto w-full">
        {actionSuccess && (
          <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-emerald-400" />
              <span>{actionSuccess}</span>
            </div>
            <button
              onClick={() => setActionSuccess(null)}
              className="text-emerald-400 hover:text-emerald-200 text-xs font-medium ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {actionError && (
          <ErrorAlert
            title="Dataset Operation Error"
            message={actionError}
            onRetry={() => loadDatasets(offset, limit)}
          />
        )}

        {/* Datasets Table Container */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Registered Datasets</h3>
              <p className="text-xs text-slate-400">
                {total} dataset{total === 1 ? '' : 's'} available for experiments
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                <tr>
                  <th className="px-6 py-3">Dataset Name</th>
                  <th className="px-6 py-3">Format & Size</th>
                  <th className="px-6 py-3">Records</th>
                  <th className="px-6 py-3">Validation Status</th>
                  <th className="px-6 py-3">Snapshots</th>
                  <th className="px-6 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {isLoading && datasets.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-400">
                      <div className="flex items-center justify-center gap-2">
                        <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
                        <span>Loading datasets...</span>
                      </div>
                    </td>
                  </tr>
                ) : datasets.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-400">
                      <Database className="h-8 w-8 text-slate-600 mx-auto mb-2" />
                      <p className="text-sm font-medium text-slate-300">No datasets found</p>
                      <p className="text-xs text-slate-400 mt-1">
                        Upload a JSON or JSONL file to get started.
                      </p>
                    </td>
                  </tr>
                ) : (
                  datasets.map((ds) => (
                    <tr key={ds.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-medium text-slate-200">{ds.display_name}</div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          {ds.original_filename}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="uppercase font-semibold text-slate-300">{ds.format}</div>
                        <div className="text-[11px] text-slate-400">
                          {(ds.size_bytes / 1024).toFixed(1)} KB
                        </div>
                      </td>
                      <td className="px-6 py-4 font-medium text-slate-200">
                        {ds.record_count}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-col items-start gap-1">
                          <StatusBadge status={ds.validation_status} size="sm" />
                          {ds.validation_errors && ds.validation_errors.length > 0 && (
                            <span className="text-[10px] text-rose-400 flex items-center gap-1 mt-0.5">
                              <AlertTriangle className="h-3 w-3" />
                              {ds.validation_errors.length} error(s)
                            </span>
                          )}
                          {ds.validation_warnings && ds.validation_warnings.length > 0 && (
                            <span className="text-[10px] text-amber-400 flex items-center gap-1 mt-0.5">
                              <AlertTriangle className="h-3 w-3" />
                              {ds.validation_warnings.length} warning(s)
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-slate-300 font-medium">
                          {ds.snapshots?.length || 0} snapshot{ds.snapshots?.length === 1 ? '' : 's'}
                        </div>
                        {ds.snapshots && ds.snapshots.length > 0 && (
                          <div className="text-[10px] text-indigo-400 font-mono mt-0.5 truncate max-w-[140px]">
                            {ds.snapshots[ds.snapshots.length - 1].name}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handleOpenRecords(ds)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700"
                            title="Inspect Records"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleRevalidate(ds.id)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700"
                            title="Re-validate"
                          >
                            <RotateCw className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => {
                              setSnapshotDataset(ds);
                              setSnapshotName(`${ds.display_name}_snapshot_${Date.now().toString().slice(-4)}`);
                            }}
                            className="p-1.5 rounded-lg bg-indigo-950/60 hover:bg-indigo-900 text-indigo-300 border border-indigo-800/60 transition-colors"
                            title="Create Immutable Snapshot"
                          >
                            <Camera className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleDelete(ds)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/60 text-slate-400 hover:text-rose-300 transition-colors border border-slate-700"
                            title="Delete Dataset"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <Pagination
            offset={offset}
            limit={limit}
            total={total}
            onPageChange={(newOffset) => setOffset(newOffset)}
            onLimitChange={(newLimit) => {
              setLimit(newLimit);
              setOffset(0);
            }}
            isLoading={isLoading}
          />
        </div>
      </main>

      {/* Upload Dataset Modal */}
      <Modal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        title="Upload Dataset"
        subtitle="Upload a raw JSON or JSONL file to evaluate AI agents"
        footer={
          <>
            <button
              type="button"
              onClick={() => setIsUploadOpen(false)}
              className="px-3.5 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              onClick={handleUpload}
              disabled={!uploadFile || isUploading}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors"
            >
              {isUploading ? (
                <>
                  <RotateCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Uploading & Validating...</span>
                </>
              ) : (
                <>
                  <Upload className="h-3.5 w-3.5" />
                  <span>Upload & Register</span>
                </>
              )}
            </button>
          </>
        }
      >
        <form onSubmit={handleUpload} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Display Name (Optional)
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g. Financial News 2026 Batch"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Dataset File (.json or .jsonl) <span className="text-rose-400">*</span>
            </label>
            <div className="border-2 border-dashed border-slate-700 hover:border-indigo-500 rounded-xl p-6 text-center cursor-pointer transition-colors bg-slate-950/40">
              <input
                type="file"
                accept=".json,.jsonl"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setUploadFile(e.target.files[0]);
                    if (!displayName) {
                      setDisplayName(e.target.files[0].name.replace(/\.[^/.]+$/, ''));
                    }
                  }
                }}
                className="hidden"
                id="dataset-file-input"
              />
              <label htmlFor="dataset-file-input" className="cursor-pointer block">
                <FileText className="h-8 w-8 text-indigo-400 mx-auto mb-2" />
                {uploadFile ? (
                  <div>
                    <span className="text-sm font-medium text-slate-200">
                      {uploadFile.name}
                    </span>
                    <p className="text-xs text-slate-400 mt-1">
                      {(uploadFile.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                ) : (
                  <div>
                    <span className="text-sm font-medium text-indigo-400 hover:underline">
                      Click to choose file
                    </span>
                    <p className="text-xs text-slate-500 mt-1">
                      Accepts standard JSON array or JSONL formatted records
                    </p>
                  </div>
                )}
              </label>
            </div>
          </div>
        </form>
      </Modal>

      {/* Create Snapshot Modal */}
      <Modal
        isOpen={!!snapshotDataset}
        onClose={() => setSnapshotDataset(null)}
        title="Create Immutable Snapshot"
        subtitle={`Generate a frozen snapshot of "${snapshotDataset?.display_name}"`}
        footer={
          <>
            <button
              type="button"
              onClick={() => setSnapshotDataset(null)}
              className="px-3.5 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              onClick={handleCreateSnapshot}
              disabled={isCreatingSnapshot}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors"
            >
              {isCreatingSnapshot ? (
                <>
                  <RotateCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Freezing...</span>
                </>
              ) : (
                <>
                  <Camera className="h-3.5 w-3.5" />
                  <span>Create Snapshot</span>
                </>
              )}
            </button>
          </>
        }
      >
        <form onSubmit={handleCreateSnapshot} className="space-y-4">
          <p className="text-xs text-slate-300 leading-relaxed">
            Snapshots copy and freeze dataset records with a SHA-256 fingerprint.
            Experiments reference snapshots to guarantee 100% reproducibility across repetitions.
          </p>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Snapshot Name
            </label>
            <input
              type="text"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              placeholder="e.g. baseline_snapshot_v1"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
        </form>
      </Modal>

      {/* Dataset Record Inspector Modal */}
      <Modal
        isOpen={!!selectedDataset}
        onClose={() => setSelectedDataset(null)}
        title={`Record Inspector: ${selectedDataset?.display_name}`}
        subtitle={`Total Records: ${recordsTotal}`}
        maxWidth="4xl"
      >
        <div className="space-y-4">
          {isLoadingRecords ? (
            <div className="p-8 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
              <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
              <span>Loading records page...</span>
            </div>
          ) : records.length === 0 ? (
            <p className="p-6 text-center text-slate-400 text-xs">No records available</p>
          ) : (
            <div className="space-y-3">
              {records.map((item) => (
                <div
                  key={item.index}
                  className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs"
                >
                  <div className="flex items-center justify-between border-b border-slate-800/80 pb-2 mb-2 font-mono text-[11px] text-indigo-400">
                    <span>Record #{item.index + 1}</span>
                  </div>
                  <JsonViewer data={item.record} maxHeight="max-h-48" />
                </div>
              ))}
            </div>
          )}

          <Pagination
            offset={recordsOffset}
            limit={recordsLimit}
            total={recordsTotal}
            onPageChange={(newOffset) => {
              if (selectedDataset) {
                loadRecords(selectedDataset.id, newOffset, recordsLimit);
              }
            }}
            onLimitChange={(newLimit) => {
              if (selectedDataset) {
                loadRecords(selectedDataset.id, 0, newLimit);
              }
            }}
            isLoading={isLoadingRecords}
          />
        </div>
      </Modal>
    </div>
  );
};

export default Datasets;
