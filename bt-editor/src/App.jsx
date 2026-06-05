import { useState, useCallback } from 'react'
import { ReactFlowProvider, useNodesState, useEdgesState } from '@xyflow/react'

import AgentHeader from './components/AgentHeader.jsx'
import NodePalette from './components/NodePalette.jsx'
import BtCanvas from './components/BtCanvas.jsx'
import PropertiesPanel from './components/PropertiesPanel.jsx'
import BtNarrator from './components/BtNarrator.jsx'

import { exportToYaml, downloadYaml, exportToZip } from './utils/yamlExporter.js'
import { importFromYaml } from './utils/yamlImporter.js'

const TUTORIAL_YAML = `
name: "simple"
version: "1.0.0"
description: "Hard Deck 회피 + 기본 추적만 하는 단순 전투기"
tree:
  type: Selector
  children:
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000
    - type: Action
      name: Pursue
`

function loadTutorial() {
  const result = importFromYaml(TUTORIAL_YAML)
  return result
}

/* ─── 리사이즈 구분선 ─── */
function VDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="w-[5px] shrink-0 cursor-col-resize relative group z-10"
    >
      <div className="absolute inset-y-0 left-[2px] w-[1px] bg-gray-700 group-hover:bg-blue-500 transition-colors" />
    </div>
  )
}

function HDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="h-[5px] shrink-0 cursor-row-resize relative group z-10"
    >
      <div className="absolute inset-x-0 top-[2px] h-[1px] bg-gray-700 group-hover:bg-blue-500 transition-colors" />
    </div>
  )
}

// ReactFlowProvider must wrap everything that uses React Flow hooks
function EditorInner() {
  const init = loadTutorial()
  const [agentName, setAgentName] = useState('simple')
  const [description, setDescription] = useState('Hard Deck 회피 + 기본 추적만 하는 단순 전투기')
  const [nodes, setNodes, onNodesChange] = useNodesState(init.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(init.edges)
  const [selectedNode, setSelectedNode] = useState(null)
  const [toast, setToast] = useState(null)

  // 커스텀 노드 — localStorage로 세션 간 유지
  const [customNodes, setCustomNodes] = useState(() => {
    try {
      const saved = localStorage.getItem('bt-custom-nodes')
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })

  function handleAddCustomNode(nodeDef) {
    setCustomNodes(prev => {
      const next = [...prev, nodeDef]
      localStorage.setItem('bt-custom-nodes', JSON.stringify(next))
      return next
    })
    showToast(`커스텀 노드 "${nodeDef.name}" 추가됨`, 'success')
  }

  function handleRemoveCustomNode(id) {
    setCustomNodes(prev => {
      const next = prev.filter(n => n.id !== id)
      localStorage.setItem('bt-custom-nodes', JSON.stringify(next))
      return next
    })
  }

  // 패널 크기 상태
  const [leftW, setLeftW] = useState(208)
  const [rightW, setRightW] = useState(224)
  const [bottomH, setBottomH] = useState(140)

  function startDrag(e, onMove) {
    e.preventDefault()
    document.body.style.cursor = window.getComputedStyle(e.currentTarget).cursor
    document.body.style.userSelect = 'none'
    const up = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', up)
  }

  function handleDragLeft(e) {
    const sx = e.clientX, sw = leftW
    startDrag(e, e => setLeftW(Math.max(140, Math.min(400, sw + e.clientX - sx))))
  }
  function handleDragRight(e) {
    const sx = e.clientX, sw = rightW
    startDrag(e, e => setRightW(Math.max(160, Math.min(420, sw - (e.clientX - sx))))  )
  }
  function handleDragBottom(e) {
    const sy = e.clientY, sh = bottomH
    startDrag(e, e => setBottomH(Math.max(60, Math.min(300, sh - (e.clientY - sy))))  )
  }

  function showToast(msg, type = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  function handleExport() {
    const { yaml: yamlStr, error } = exportToYaml(agentName, description, nodes, edges)
    if (error) { showToast(error, 'error'); return }
    downloadYaml(yamlStr, agentName || 'my_agent')
    showToast(`${agentName}.yaml 다운로드 완료!`, 'success')
  }

  async function handleExportZip() {
    const { error } = await exportToZip(agentName, description, nodes, edges, customNodes)
    if (error) { showToast(error, 'error'); return }
    showToast(`${agentName}.zip 다운로드 완료! submissions/ 폴더에 압축 해제하세요.`, 'success')
  }

  function handleReset() {
    const { nodes: n, edges: e, meta } = loadTutorial()
    setNodes(n)
    setEdges(e)
    setAgentName(meta.name)
    setDescription(meta.description)
    setSelectedNode(null)
    showToast('튜토리얼 트리로 초기화했습니다.', 'info')
  }

  function handleImport(yamlStr) {
    try {
      const { nodes: newNodes, edges: newEdges, meta } = importFromYaml(yamlStr)
      setNodes(newNodes)
      setEdges(newEdges)
      setAgentName(meta.name)
      setDescription(meta.description)
      setSelectedNode(null)
      showToast(`"${meta.name}" 불러오기 완료! (노드 ${newNodes.length}개)`, 'success')
    } catch (e) {
      showToast(e.message, 'error')
    }
  }

  const handleNodeSelect = useCallback((node) => {
    setSelectedNode(node)
  }, [])

  const handleUpdateNode = useCallback((nodeId, dataUpdate) => {
    setNodes(nds =>
      nds.map(n =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, ...dataUpdate } }
          : n
      )
    )
    setSelectedNode(prev =>
      prev && prev.id === nodeId
        ? { ...prev, data: { ...prev.data, ...dataUpdate } }
        : prev
    )
  }, [setNodes])

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white overflow-hidden">
      <AgentHeader
        agentName={agentName}
        setAgentName={setAgentName}
        description={description}
        setDescription={setDescription}
        onExport={handleExport}
        onExportZip={handleExportZip}
        onImport={handleImport}
        onReset={handleReset}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* 왼쪽 팔레트 */}
        <div style={{ width: leftW }} className="shrink-0 overflow-hidden border-r border-gray-700">
          <NodePalette
            customNodes={customNodes}
            onAddCustomNode={handleAddCustomNode}
            onRemoveCustomNode={handleRemoveCustomNode}
          />
        </div>
        <VDivider onMouseDown={handleDragLeft} />

        {/* 중앙 캔버스 + 하단 해설 */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <BtCanvas
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            setNodes={setNodes}
            onEdgesChange={onEdgesChange}
            setEdges={setEdges}
            onNodeSelect={handleNodeSelect}
            customNodes={customNodes}
          />
          <HDivider onMouseDown={handleDragBottom} />
          <div style={{ height: bottomH }} className="shrink-0 overflow-hidden">
            <BtNarrator nodes={nodes} edges={edges} />
          </div>
        </div>

        {/* 오른쪽 파라미터 패널 */}
        <VDivider onMouseDown={handleDragRight} />
        <div style={{ width: rightW }} className="shrink-0 overflow-hidden border-l border-gray-700">
          <PropertiesPanel
            selectedNode={selectedNode}
            onUpdateNode={handleUpdateNode}
            customNodes={customNodes}
          />
        </div>
      </div>

      {toast && (
        <div
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2 rounded-lg shadow-lg text-sm font-medium z-50
            ${toast.type === 'error' ? 'bg-red-600 text-white' : toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-gray-700 text-white'}`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <EditorInner />
    </ReactFlowProvider>
  )
}
