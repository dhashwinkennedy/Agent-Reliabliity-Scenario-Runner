import React, { useState } from 'react';
import {
  AgentFieldDef,
  ExtractedDatasetFields,
  MappingValidationResult,
} from '../../utils/inputMapping';
import JsonViewer from '../JsonViewer';

interface InputFieldMappingProps {
  agentFields: AgentFieldDef[];
  datasetFields: ExtractedDatasetFields;
  mapping: Record<string, string>;
  onChange: (newMapping: Record<string, string>) => void;
  validationResult: MappingValidationResult;
  sampleRecord?: Record<string, unknown> | null;
  onAutoResolve: () => void;
}

export const InputFieldMapping: React.FC<InputFieldMappingProps> = ({
  agentFields,
  datasetFields,
  mapping,
  onChange,
  validationResult,
  sampleRecord,
  onAutoResolve,
}) => {
  const [showSample, setShowSample] = useState(false);

  const handleFieldChange = (targetField: string, sourcePath: string) => {
    onChange({
      ...mapping,
      [targetField]: sourcePath,
    });
  };

  const handleReset = () => {
    const empty: Record<string, string> = {};
    for (const f of agentFields) {
      empty[f.name] = '';
    }
    onChange(empty);
  };

  const requiredCount = agentFields.filter((f) => f.required).length;
  const mappedRequiredCount = agentFields.filter(
    (f) => f.required && (mapping[f.name] || '').trim() !== ''
  ).length;

  return (
    <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-200 text-sm">
              Input Field Mapping
            </span>
            <span className="px-2 py-0.5 text-[11px] font-medium bg-slate-800 text-slate-300 rounded-full border border-slate-700">
              {agentFields.length} Fields ({mappedRequiredCount}/{requiredCount} Required Mapped)
            </span>
          </div>
          <p className="text-[12px] text-slate-400 mt-0.5">
            Resolve agent input contract fields against dataset record fields.
            Ground truth and evaluator metadata are strictly isolated.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onAutoResolve}
            className="px-2.5 py-1 text-xs font-medium bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 rounded-lg hover:bg-indigo-600/30 transition-colors flex items-center gap-1.5"
            title="Auto-match fields using benchmark input names and aliases"
          >
            <svg
              className="w-3.5 h-3.5 text-indigo-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
            Auto-Resolve
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="px-2.5 py-1 text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700 rounded-lg hover:bg-slate-700 hover:text-slate-200 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Validation Banner */}
      {!validationResult.isValid ? (
        <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded-lg text-rose-200 text-xs space-y-1.5">
          <div className="flex items-center gap-2 font-medium text-rose-300">
            <svg
              className="w-4 h-4 text-rose-400 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <span>Mapping Incomplete: {validationResult.missingRequired.length} required field(s) unmapped</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-rose-300/90 pl-1">
            {validationResult.errors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="p-2.5 bg-emerald-950/30 border border-emerald-800/40 rounded-lg text-emerald-300 text-xs flex items-center gap-2">
          <svg
            className="w-4 h-4 text-emerald-400 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
          <span>All required agent input fields are validly mapped</span>
        </div>
      )}

      {/* Mapping Rows Table */}
      <div className="border border-slate-800 rounded-lg overflow-hidden bg-slate-900/60">
        <div className="max-h-72 overflow-y-auto divide-y divide-slate-800/60">
          {agentFields.map((field) => {
            const currentSource = mapping[field.name] || '';
            const isMapped = currentSource.trim() !== '';
            const isMissing = field.required && !isMapped;

            return (
              <div
                key={field.name}
                className={`p-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs transition-colors ${
                  isMissing
                    ? 'bg-rose-950/10'
                    : isMapped
                    ? 'hover:bg-slate-850/40'
                    : 'hover:bg-slate-850/20'
                }`}
              >
                {/* Agent Target Field Definition */}
                <div className="sm:w-1/2 flex flex-col justify-center">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-mono font-medium text-slate-200">
                      {field.name}
                    </span>
                    {field.required ? (
                      <span className="text-rose-400 font-bold" title="Required agent field">
                        *
                      </span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.2 bg-slate-800 text-slate-400 rounded">
                        optional
                      </span>
                    )}
                    <span className="text-[10px] font-mono px-1.5 py-0.2 bg-slate-800/80 text-indigo-300/80 rounded border border-slate-700/60">
                      {field.type}
                    </span>
                  </div>
                  {field.description && (
                    <span className="text-[11px] text-slate-400 mt-0.5 line-clamp-1">
                      {field.description}
                    </span>
                  )}
                </div>

                {/* Arrow Indicator */}
                <div className="hidden sm:flex items-center justify-center text-slate-500 font-bold">
                  ←
                </div>

                {/* Dataset Source Dropdown */}
                <div className="sm:w-5/12 flex items-center gap-2">
                  <select
                    value={currentSource}
                    onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    className={`w-full bg-slate-800 border text-xs rounded-lg px-2.5 py-1.5 text-slate-100 font-mono focus:outline-none focus:ring-1 ${
                      isMissing
                        ? 'border-rose-700/80 focus:ring-rose-500 bg-rose-950/20'
                        : 'border-slate-700 focus:ring-indigo-500'
                    }`}
                  >
                    <option value="">-- Not Mapped (Unset) --</option>

                    {datasetFields.nestedInput.length > 0 && (
                      <optgroup label="Nested in 'input' object (Benchmark)">
                        {datasetFields.nestedInput.map((f) => (
                          <option key={f.path} value={f.path}>
                            {f.path} ({f.type})
                          </option>
                        ))}
                      </optgroup>
                    )}

                    {datasetFields.topLevel.length > 0 && (
                      <optgroup label="Top-level record fields">
                        {datasetFields.topLevel.map((f) => (
                          <option key={f.path} value={f.path}>
                            {f.path} ({f.type})
                          </option>
                        ))}
                      </optgroup>
                    )}

                    {/* Preserve custom/existing value if not currently in datasetFields options */}
                    {currentSource &&
                      !datasetFields.all.some((f) => f.path === currentSource) && (
                        <optgroup label="Current custom mapping">
                          <option value={currentSource}>{currentSource}</option>
                        </optgroup>
                      )}
                  </select>

                  {/* Status Indicator Pill */}
                  <div className="flex-shrink-0">
                    {isMapped ? (
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500"
                        title="Mapped"
                      />
                    ) : field.required ? (
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse"
                        title="Required but unmapped"
                      />
                    ) : (
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full bg-slate-600"
                        title="Optional unmapped"
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sample Record Inspector Toggle */}
      {sampleRecord && (
        <div className="pt-2 border-t border-slate-800/80">
          <div className="flex items-center justify-between mb-1.5">
            <button
              type="button"
              onClick={() => setShowSample((prev) => !prev)}
              className="text-[11px] font-medium text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
            >
              <span>{showSample ? '▼ Hide Sample Record' : '▶ Inspect Sample Record from Dataset'}</span>
            </button>
            <span className="text-[10px] text-slate-500">
              Evaluator ground truth & metadata are isolated
            </span>
          </div>

          {showSample && (
            <div className="mt-2 space-y-1">
              <JsonViewer data={sampleRecord} maxHeight="max-h-48" />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default InputFieldMapping;
