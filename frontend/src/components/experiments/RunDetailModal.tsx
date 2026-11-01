import React from 'react';
import type { Run, RunResult } from '../../types';
import Modal from '../Modal';
import StatusBadge from '../StatusBadge';
import JsonViewer from '../JsonViewer';
import { ShieldCheck, AlertCircle, Clock, Zap } from 'lucide-react';
import { parseError, ErrorText } from '../../utils/error';

interface RunDetailModalProps {
  run: Run | RunResult | null;
  onClose: () => void;
}

export const RunDetailModal: React.FC<RunDetailModalProps> = ({ run, onClose }) => {
  if (!run) return null;

  const runId = 'id' in run ? run.id : run.run_id;
  const input = 'input_data' in run ? run.input_data : run.input;
  const output = 'output_data' in run ? run.output_data : 'output' in run ? (run as RunResult).output : null;
  const error = run.error;

  // Check for EGAL audit attributes in output
  const egalAudit: unknown = output && typeof output === 'object' && ('audit' in output || 'egal_audit' in output)
    ? ((output as Record<string, unknown>).audit || (output as Record<string, unknown>).egal_audit)
    : null;

  const uncertaintyScore = output && typeof output === 'object' && 'uncertainty_score' in output
    ? (output as Record<string, unknown>).uncertainty_score
    : null;

  const abstentionReason = output && typeof output === 'object' && 'abstention_reason' in output
    ? (output as Record<string, unknown>).abstention_reason
    : null;

  return (
    <Modal
      isOpen={!!run}
      onClose={onClose}
      title={`Run Details: ${runId}`}
      subtitle={`Dataset Item: ${run.dataset_item_id} • Repetition ${run.repetition_index || 1}`}
      maxWidth="2xl"
    >
      <div className="space-y-5">
        {/* Run Metadata Bar */}
        <div className="flex items-center justify-between p-3.5 bg-slate-950 rounded-lg border border-slate-800 text-xs">
          <div className="flex items-center gap-3">
            <StatusBadge status={run.status} size="sm" />
            {run.latency_ms !== undefined && run.latency_ms !== null && (
              <span className="flex items-center gap-1 text-slate-400">
                <Clock className="h-3.5 w-3.5 text-slate-400" />
                <span>{run.latency_ms.toFixed(1)} ms</span>
              </span>
            )}
            {run.tokens_used !== undefined && run.tokens_used !== null && (
              <span className="flex items-center gap-1 text-slate-400">
                <Zap className="h-3.5 w-3.5 text-amber-400" />
                <span>{run.tokens_used} tokens</span>
              </span>
            )}
          </div>
        </div>

        {/* Error banner if failed */}
        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg text-xs text-rose-300 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold block mb-1">Execution Error:</span>
              <ErrorText error={error} className="font-mono text-slate-200" />
            </div>
          </div>
        )}

        {/* EGAL Audit Information if present */}
        {(egalAudit || uncertaintyScore !== null || abstentionReason !== null) && (
          <div className="p-4 bg-indigo-950/40 border border-indigo-500/30 rounded-xl space-y-3">
            <div className="flex items-center gap-2 text-indigo-300 font-semibold text-xs">
              <ShieldCheck className="h-4 w-4 text-indigo-400" />
              <span>EGAL Guardrails & Verification Audit</span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              {uncertaintyScore !== null && (
                <div className="p-2.5 bg-slate-900/80 rounded border border-indigo-900/60">
                  <span className="text-[11px] text-slate-400 block">Uncertainty Score</span>
                  <span className="text-sm font-bold text-slate-100 font-mono">
                    {String(uncertaintyScore)}
                  </span>
                </div>
              )}
              {abstentionReason !== null && (
                <div className="p-2.5 bg-slate-900/80 rounded border border-indigo-900/60">
                  <span className="text-[11px] text-slate-400 block">Abstention Reason</span>
                  <span className="text-xs font-medium text-amber-300">
                    {String(abstentionReason)}
                  </span>
                </div>
              )}
            </div>

            {!!egalAudit && (
              <div className="mt-2">
                <span className="text-[11px] text-slate-400 block mb-1 font-medium">
                  Audit Trail Trace:
                </span>
                <JsonViewer data={egalAudit} maxHeight="max-h-40" />
              </div>
            )}
          </div>
        )}

        {/* Input Data */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
            Input Payload
          </h4>
          <JsonViewer data={input} maxHeight="max-h-52" />
        </div>

        {/* Output Data */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
            Agent Output
          </h4>
          <JsonViewer data={output || { note: 'No output recorded' }} maxHeight="max-h-52" />
        </div>

        {/* Ground Truth if in RunResult */}
        {'ground_truth' in run && run.ground_truth && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
              Ground Truth
            </h4>
            <JsonViewer data={run.ground_truth} maxHeight="max-h-40" />
          </div>
        )}
      </div>
    </Modal>
  );
};

export default RunDetailModal;
