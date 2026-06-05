import { Handle, Position } from '@xyflow/react'

const COLORS = {
  Selector: { border: 'border-purple-500', bg: 'bg-purple-900', header: 'bg-purple-700', text: 'text-purple-200', badge: 'OR' },
  Sequence: { border: 'border-purple-400', bg: 'bg-purple-950', header: 'bg-purple-600', text: 'text-purple-100', badge: 'AND' },
  Parallel: { border: 'border-violet-400', bg: 'bg-violet-950', header: 'bg-violet-600', text: 'text-violet-100', badge: '∥' },
}

export default function CompositeNode({ data, selected }) {
  const c = COLORS[data.name] || COLORS.Selector
  const hasError = data.error

  return (
    <div
      className={`rounded-lg border-2 min-w-[130px] shadow-lg ${c.border} ${c.bg} ${selected ? 'ring-2 ring-white/50' : ''} ${hasError ? 'ring-2 ring-red-500' : ''}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400 !w-3 !h-3" />

      <div className={`${c.header} rounded-t-md px-3 py-1.5 flex items-center gap-2`}>
        <span className={`text-xs font-bold px-1.5 py-0.5 rounded bg-white/20 ${c.text}`}>{c.badge}</span>
        <span className="text-white text-sm font-semibold">{data.name}</span>
      </div>

      {data.label && (
        <div className="px-3 py-1 text-gray-400 text-xs italic truncate max-w-[160px]">{data.label}</div>
      )}

      {data.name === 'Parallel' && data.params?.policy && (
        <div className="px-3 pb-1.5 text-xs text-violet-300">{data.params.policy}</div>
      )}

      {hasError && (
        <div className="px-3 pb-1.5 text-xs text-red-400">⚠ 자식 노드 필요</div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 !w-3 !h-3" />
    </div>
  )
}
