import { useCallback } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import CompositeNode from './CustomNodes/CompositeNode.jsx'
import ConditionNode from './CustomNodes/ConditionNode.jsx'
import ActionNode from './CustomNodes/ActionNode.jsx'
import ValidationPanel, { useValidation } from './ValidationPanel.jsx'
import ObsLegend from './ObsLegend.jsx'
import manifest from '../data/nodes-manifest.json'
import { applyDagreLayout } from '../utils/treeLayout.js'

const nodeTypes = {
  compositeNode: CompositeNode,
  conditionNode: ConditionNode,
  actionNode: ActionNode,
}

const ALL_NODE_DEFS = [
  ...manifest.composites.map(n => ({ ...n, category: 'composites' })),
  ...manifest.conditions.map(n => ({ ...n, category: 'conditions' })),
  ...manifest.actions.map(n => ({ ...n, category: 'actions' })),
]

function categoryToNodeType(category) {
  if (category === 'composites') return 'compositeNode'
  if (category === 'conditions') return 'conditionNode'
  return 'actionNode'
}

function getDefaultParams(nodeName, customNodes = []) {
  const def = ALL_NODE_DEFS.find(n => n.name === nodeName)
    || customNodes.find(n => n.name === nodeName)
  if (!def || !def.params) return {}
  const params = {}
  def.params.forEach(p => { params[p.key] = p.default })
  return params
}

let idCounter = 0
function uid() { return `node_${++idCounter}_${Date.now()}` }

export default function BtCanvas({ nodes, edges, onNodesChange, setNodes, onEdgesChange, setEdges, onNodeSelect, customNodes = [] }) {
  const { screenToFlowPosition } = useReactFlow()
  const warnings = useValidation(nodes, edges)

  const onConnect = useCallback((params) => {
    setEdges(eds => addEdge({ ...params, type: 'smoothstep' }, eds))
  }, [setEdges])

  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/bt-node')
    if (!raw) return

    const { name, category } = JSON.parse(raw)
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })

    const newNode = {
      id: uid(),
      type: categoryToNodeType(category),
      position,
      data: {
        name,
        category,
        params: getDefaultParams(name, customNodes),
        label: '',
      },
    }

    setNodes(nds => [...nds, newNode])
  }, [screenToFlowPosition, setNodes, customNodes])

  const onSelectionChange = useCallback(({ nodes: selected }) => {
    if (selected.length === 1) {
      onNodeSelect(selected[0])
    } else {
      onNodeSelect(null)
    }
  }, [onNodeSelect])

  function handleAutoLayout() {
    setNodes(nds => applyDagreLayout(nds, edges))
  }

  return (
    <div className="flex-1 relative bg-gray-950">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onSelectionChange={onSelectionChange}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode="Delete"
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#374151" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={node => {
            if (node.type === 'compositeNode') return '#7c3aed'
            if (node.type === 'conditionNode') return '#2563eb'
            return '#ea580c'
          }}
          bgColor="#111827"
          maskColor="#111827aa"
        />
      </ReactFlow>

      <ValidationPanel warnings={warnings} />
      <ObsLegend />

      {nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center text-gray-600">
            <div className="text-5xl mb-3">🌳</div>
            <p className="text-lg font-semibold">왼쪽 팔레트에서 노드를 드래그하세요</p>
            <p className="text-sm mt-1">Selector나 Sequence로 시작하는 것을 추천합니다</p>
          </div>
        </div>
      )}

      <button
        onClick={handleAutoLayout}
        className="absolute bottom-4 right-4 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded shadow transition-colors z-10"
        title="노드를 트리 형태로 자동 정렬"
      >
        ⟳ 자동 정렬
      </button>
    </div>
  )
}
