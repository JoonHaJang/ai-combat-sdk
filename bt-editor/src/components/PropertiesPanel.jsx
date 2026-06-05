import manifest from '../data/nodes-manifest.json'
import TacticalDiagram from './TacticalDiagram.jsx'

const ALL_DEFS = [
  ...manifest.composites,
  ...manifest.conditions,
  ...manifest.actions,
]

function getNodeDef(name, customNodes = []) {
  return ALL_DEFS.find(n => n.name === name) || customNodes.find(n => n.name === name) || null
}

function ParamField({ paramDef, value, onChange }) {
  const { key, type, options, unit, description } = paramDef

  return (
    <div className="mb-3">
      <label className="block text-xs text-gray-400 mb-0.5">
        {key} {unit && <span className="text-gray-600">({unit})</span>}
      </label>
      {description && <p className="text-gray-600 text-xs mb-1">{description}</p>}

      {type === 'number' && (
        <input
          type="number"
          value={value ?? paramDef.default}
          onChange={e => onChange(key, parseFloat(e.target.value))}
          className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
        />
      )}

      {type === 'select' && (
        <select
          value={value ?? paramDef.default}
          onChange={e => onChange(key, e.target.value)}
          className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
        >
          {options.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      )}

      {type === 'string' && (
        <input
          type="text"
          value={value ?? paramDef.default}
          onChange={e => onChange(key, e.target.value)}
          className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
        />
      )}
    </div>
  )
}

export default function PropertiesPanel({ selectedNode, onUpdateNode, customNodes = [] }) {
  if (!selectedNode) {
    return (
      <aside className="w-full h-full bg-gray-900 flex flex-col items-center justify-center p-4">
        <div className="text-center text-gray-600">
          <div className="text-3xl mb-2">⚙️</div>
          <p className="text-xs">노드를 클릭하면<br />파라미터를 편집합니다</p>
        </div>
      </aside>
    )
  }

  const { data, id } = selectedNode
  const def = getNodeDef(data.name, customNodes)

  function handleParamChange(key, value) {
    onUpdateNode(id, { params: { ...data.params, [key]: value } })
  }

  function handleLabelChange(e) {
    onUpdateNode(id, { label: e.target.value })
  }

  const categoryLabel = { composites: 'Composite', conditions: 'Condition', actions: 'Action' }[data.category]
  const categoryColor = { composites: 'text-purple-400', conditions: 'text-blue-400', actions: 'text-orange-400' }[data.category]

  return (
    <aside className="w-full h-full bg-gray-900 overflow-y-auto">
      <div className="p-3 border-b border-gray-700">
        <span className={`text-xs font-semibold ${categoryColor}`}>{categoryLabel}</span>
        <h2 className="text-white text-base font-bold mt-0.5">{data.name}</h2>
        {def?.koreanName && (
          <p className="text-gray-400 text-xs mt-0.5">{def.koreanName}</p>
        )}
        {def?.diagramType && (
          <div className="mt-2">
            <TacticalDiagram type={def.diagramType} />
          </div>
        )}
        {def?.description && (
          <p className="text-gray-500 text-xs mt-1 leading-relaxed">{def.description}</p>
        )}
      </div>

      <div className="p-3">
        <div className="mb-3">
          <label className="block text-xs text-gray-400 mb-0.5">노드 레이블 (선택)</label>
          <input
            type="text"
            value={data.label || ''}
            onChange={handleLabelChange}
            placeholder="예: 공격 분기"
            className="w-full bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
          />
        </div>

        {def?.params?.length > 0 && (
          <>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-2 border-t border-gray-700 pt-2">파라미터</div>
            {def.params.map(paramDef => (
              <ParamField
                key={paramDef.key}
                paramDef={paramDef}
                value={data.params?.[paramDef.key]}
                onChange={handleParamChange}
              />
            ))}
          </>
        )}

        {(!def?.params || def.params.length === 0) && (
          <p className="text-gray-600 text-xs">파라미터 없음</p>
        )}
      </div>
    </aside>
  )
}
