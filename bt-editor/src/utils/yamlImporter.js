import yaml from 'js-yaml'
import { applyDagreLayout } from './treeLayout.js'

let idCounter = 0
function uid() { return `node_${++idCounter}_${Date.now()}` }

function categoryOf(type) {
  if (['Selector', 'Sequence', 'Parallel'].includes(type)) return 'composites'
  if (type === 'Condition') return 'conditions'
  if (type === 'Action') return 'actions'
  return 'composites'
}

/**
 * YAML 문자열 → { nodes, edges }
 */
export function importFromYaml(yamlStr) {
  let doc
  try {
    doc = yaml.load(yamlStr)
  } catch (e) {
    throw new Error(`YAML 파싱 오류: ${e.message}`)
  }

  if (!doc || !doc.tree) {
    throw new Error('tree 항목을 찾을 수 없습니다.')
  }

  const nodes = []
  const edges = []

  function walk(treeNode, parentId) {
    const id = uid()
    const { type, name, params, children, name_label } = treeNode
    const category = categoryOf(type)

    // composites: name = type (Selector/Sequence/Parallel)
    // conditions/actions: name = name field
    const nodeName = category === 'composites' ? type : (name || type)

    nodes.push({
      id,
      type: category === 'composites' ? 'compositeNode' : category === 'conditions' ? 'conditionNode' : 'actionNode',
      position: { x: 0, y: 0 },
      data: {
        name: nodeName,
        category,
        params: params || {},
        label: name_label || '',
      },
    })

    if (parentId) {
      edges.push({
        id: `e_${parentId}_${id}`,
        source: parentId,
        target: id,
        type: 'smoothstep',
        animated: false,
      })
    }

    if (Array.isArray(children)) {
      children.forEach(child => walk(child, id))
    }
  }

  walk(doc.tree, null)

  const layoutedNodes = applyDagreLayout(nodes, edges)

  return {
    nodes: layoutedNodes,
    edges,
    meta: {
      name: doc.name || 'my_agent',
      description: doc.description || '',
    },
  }
}
