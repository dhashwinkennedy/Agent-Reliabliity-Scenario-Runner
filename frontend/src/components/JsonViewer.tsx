import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface JsonViewerProps {
  data: unknown;
  maxHeight?: string;
  title?: string;
}

export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  maxHeight = 'max-h-96',
  title,
}) => {
  const [copied, setCopied] = useState(false);
  const jsonString = JSON.stringify(data, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-lg border border-slate-800 bg-slate-950 overflow-hidden font-mono text-xs">
      {title && (
        <div className="flex items-center justify-between px-3 py-2 bg-slate-900 border-b border-slate-800 text-[11px] text-slate-400 font-medium font-sans">
          <span>{title}</span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-slate-400 hover:text-slate-200 transition-colors"
            title="Copy JSON"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" />
                <span className="text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      )}

      {!title && (
        <button
          onClick={handleCopy}
          className="absolute top-2 right-2 p-1.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors z-10"
          title="Copy JSON"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      )}

      <pre className={`p-4 overflow-auto text-slate-300 leading-relaxed ${maxHeight}`}>
        {jsonString}
      </pre>
    </div>
  );
};

export default JsonViewer;
