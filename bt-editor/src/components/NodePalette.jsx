import { useState, useRef } from 'react'
import manifest from '../data/nodes-manifest.json'
import TacticalDiagram from './TacticalDiagram.jsx'
import CustomNodeModal from './CustomNodeModal.jsx'

const CATEGORY_COLORS = {
  composites: { bg: 'bg-purple-700', hover: 'hover:bg-purple-600', dot: 'bg-purple-400', label: 'Composites' },
  conditions:  { bg: 'bg-blue-700',   hover: 'hover:bg-blue-600',   dot: 'bg-blue-400',   label: 'Conditions' },
  actions:     { bg: 'bg-orange-700', hover: 'hover:bg-orange-600', dot: 'bg-orange-400', label: 'Actions' },
}

const CATEGORY_TAG = { composites: 'OR/AND', conditions: 'IF', actions: 'DO' }

function RichTooltip({ node, category }) {
  const colors = CATEGORY_COLORS[category]
  const tag = CATEGORY_TAG[category]

  return (
    <div className="w-72 bg-gray-900 border border-gray-600 rounded-lg shadow-2xl p-3 pointer-events-none">
      {/* 헤더 */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${colors.bg} text-white`}>{tag}</span>
        <span className="text-white font-semibold text-sm">{node.name}</span>
      </div>

      {/* 한국어 이름 */}
      {node.koreanName && (
        <div className="text-gray-300 text-xs font-medium mb-1.5">🇰🇷 {node.koreanName}</div>
      )}

      {/* 전술 다이어그램 */}
      {node.diagramType && <TacticalDiagram type={node.diagramType} />}

      {/* 설명 */}
      <p className="text-gray-400 text-xs leading-relaxed mb-2">{node.description}</p>

      {/* 파라미터 요약 */}
      {node.params.length > 0 && (
        <div className="mb-2 border-t border-gray-700 pt-2">
          <div className="text-gray-500 text-xs mb-1">⚙ 기본 파라미터</div>
          {node.params.map(p => (
            <div key={p.key} className="flex justify-between text-xs">
              <span className="text-gray-500">{p.key}</span>
              <span className="text-gray-300 font-mono">{p.default} {p.unit}</span>
            </div>
          ))}
        </div>
      )}

      {/* 전술 팁 */}
      {node.tacticalTip && (
        <div className="border-t border-gray-700 pt-2">
          <div className="text-yellow-400 text-xs font-semibold mb-1">💡 전술 팁</div>
          <p className="text-yellow-200/80 text-xs leading-relaxed">{node.tacticalTip}</p>
        </div>
      )}
    </div>
  )
}

function PaletteNode({ node, category }) {
  const colors = CATEGORY_COLORS[category]
  const [tooltipPos, setTooltipPos] = useState(null)
  const ref = useRef(null)

  function onDragStart(e) {
    e.dataTransfer.setData('application/bt-node', JSON.stringify({ name: node.name, category }))
    e.dataTransfer.effectAllowed = 'copy'
    setTooltipPos(null)
  }

  function onMouseEnter() {
    if (!ref.current) return
    const rect = ref.current.getBoundingClientRect()
    // 팔레트 오른쪽에 표시 (팔레트 너비 208px)
    setTooltipPos({ top: rect.top, left: rect.right + 6 })
  }

  function onMouseLeave() {
    setTooltipPos(null)
  }

  return (
    <>
      <div
        ref={ref}
        draggable
        onDragStart={onDragStart}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-grab active:cursor-grabbing ${colors.bg} ${colors.hover} text-white text-xs transition-colors select-none`}
      >
        <span className={`w-2 h-2 rounded-full ${colors.dot} shrink-0`} />
        <span className="font-mono">{node.name}</span>
        {node.koreanName && (
          <span className="ml-1 text-white/50 truncate max-w-[60px]">{node.koreanName}</span>
        )}
        {node.params.length > 0 && (
          <span className="ml-auto text-white/40 text-xs shrink-0">⚙</span>
        )}
      </div>

      {tooltipPos && (
        <div
          className="fixed z-50"
          style={{ top: Math.min(tooltipPos.top, window.innerHeight - 320), left: tooltipPos.left }}
        >
          <RichTooltip node={node} category={category} />
        </div>
      )}
    </>
  )
}

function Section({ category, nodes, searchQuery }) {
  const [open, setOpen] = useState(true)
  const colors = CATEGORY_COLORS[category]
  const filtered = nodes.filter(n =>
    n.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (n.koreanName && n.koreanName.includes(searchQuery))
  )
  if (filtered.length === 0) return null

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full px-2 py-1 text-left text-gray-300 hover:text-white text-xs font-semibold uppercase tracking-wider transition-colors"
      >
        <span>{open ? '▾' : '▸'}</span>
        <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
        <span>{colors.label}</span>
        <span className="ml-auto text-gray-500 normal-case font-normal">{filtered.length}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-0.5 px-1">
          {filtered.map(node => (
            <PaletteNode key={node.name} node={node} category={category} />
          ))}
        </div>
      )}
    </div>
  )
}

function CustomSection({ customNodes, onRemoveCustomNode, searchQuery }) {
  const [open, setOpen] = useState(true)

  const filtered = customNodes.filter(n =>
    n.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (n.description && n.description.includes(searchQuery))
  )

  if (filtered.length === 0 && !open) return null

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full px-2 py-1 text-left text-gray-300 hover:text-white text-xs font-semibold uppercase tracking-wider transition-colors"
      >
        <span>{open ? '▾' : '▸'}</span>
        <span className="w-2 h-2 rounded-full bg-teal-400 shrink-0" />
        <span>커스텀</span>
        <span className="ml-auto text-gray-500 normal-case font-normal">{filtered.length}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-0.5 px-1">
          {filtered.map(node => (
            <CustomPaletteNode
              key={node.id}
              node={node}
              onRemove={() => onRemoveCustomNode(node.id)}
            />
          ))}
          {filtered.length === 0 && (
            <p className="text-gray-600 text-xs px-2 py-1 italic">일치하는 커스텀 노드 없음</p>
          )}
        </div>
      )}
    </div>
  )
}

function CustomPaletteNode({ node, onRemove }) {
  const isAction = node.category === 'actions'
  const colorBg = isAction ? 'bg-teal-800 hover:bg-teal-700' : 'bg-cyan-800 hover:bg-cyan-700'
  const colorDot = isAction ? 'bg-teal-400' : 'bg-cyan-400'

  function onDragStart(e) {
    e.dataTransfer.setData('application/bt-node', JSON.stringify({ name: node.name, category: node.category }))
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-grab active:cursor-grabbing ${colorBg} text-white text-xs transition-colors select-none group`}
    >
      <span className={`w-2 h-2 rounded-full ${colorDot} shrink-0`} />
      <span className="font-mono flex-1 min-w-0 truncate">{node.name}</span>
      <span className="text-white/40 text-[10px] shrink-0">
        {isAction ? 'DO' : 'IF'}
      </span>
      <button
        onMouseDown={e => { e.stopPropagation(); e.preventDefault() }}
        onClick={e => { e.stopPropagation(); onRemove() }}
        className="opacity-0 group-hover:opacity-100 text-white/40 hover:text-red-400 text-xs leading-none transition-opacity shrink-0"
        title="삭제"
      >×</button>
    </div>
  )
}

export default function NodePalette({ customNodes = [], onAddCustomNode, onRemoveCustomNode }) {
  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)

  function handleSave(nodeDef) {
    onAddCustomNode(nodeDef)
    setShowModal(false)
  }

  return (
    <>
      <aside className="flex flex-col w-full h-full bg-gray-900 overflow-hidden">
        <div className="px-2 py-2 border-b border-gray-700">
          <p className="text-gray-400 text-xs mb-1.5">노드를 캔버스로 드래그하세요</p>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="노드 검색 (한국어 가능)..."
            className="w-full bg-gray-800 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
          />
        </div>
        <div className="flex-1 overflow-y-auto p-1">
          <Section category="composites" nodes={manifest.composites} searchQuery={search} />
          <Section category="conditions" nodes={manifest.conditions} searchQuery={search} />
          <Section category="actions" nodes={manifest.actions} searchQuery={search} />
          <CustomSection
            customNodes={customNodes}
            onRemoveCustomNode={onRemoveCustomNode}
            searchQuery={search}
          />
        </div>
        <div className="px-2 py-1.5 border-t border-gray-700 space-y-1">
          <button
            onClick={() => setShowModal(true)}
            className="w-full text-xs px-2 py-1.5 bg-teal-700 hover:bg-teal-600 text-white rounded transition-colors font-medium"
          >
            + 커스텀 노드 추가
          </button>
          <div className="text-gray-600 text-xs text-center">
            {manifest.composites.length + manifest.conditions.length + manifest.actions.length + customNodes.length}개 노드
          </div>
        </div>
      </aside>

      {showModal && (
        <CustomNodeModal
          onSave={handleSave}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  )
}
