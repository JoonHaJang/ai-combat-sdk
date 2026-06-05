import { Handle, Position } from '@xyflow/react'

export default function ConditionNode({ data, selected }) {
  const hasParams = data.params && Object.keys(data.params).length > 0

  return (
    <div
      className={`rounded-lg border-2 border-blue-500 bg-blue-950 min-w-[140px] shadow-lg
        ${selected ? 'ring-2 ring-white/50' : ''}
        ${data.error ? 'ring-2 ring-red-500' : ''}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 !w-3 !h-3" />

      <div className="bg-blue-700 rounded-t-md px-3 py-1.5 flex items-center gap-2">
        <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-white/20 text-blue-100">IF</span>
        <span className="text-white text-sm font-semibold truncate max-w-[110px]">{data.name}</span>
      </div>

      {hasParams && (
        <div className="px-3 py-1.5 flex flex-col gap-0.5">
          {Object.entries(data.params).map(([k, v]) => (
            <div key={k} className="flex items-center gap-1 text-xs">
              <span className="text-blue-400 truncate max-w-[70px]">{k}:</span>
              <span className="text-blue-100 font-mono">{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {data.error && (
        <div className="px-3 pb-1.5 text-xs text-red-400">{data.error}</div>
      )}

      {/* Conditions are leaf nodes — no source handle by default */}
    </div>
  )
}
