import yaml from 'js-yaml'
import JSZip from 'jszip'

/**
 * ReactFlow nodes/edges → YAML 문자열
 * @param {string} agentName
 * @param {string} description
 * @param {Array} nodes  ReactFlow nodes
 * @param {Array} edges  ReactFlow edges
 * @returns {{ yaml: string, error: string|null }}
 */
export function exportToYaml(agentName, description, nodes, edges) {
  if (nodes.length === 0) {
    return { yaml: null, error: '캔버스가 비어 있습니다.' }
  }

  // 각 노드의 자식 목록 구성 (edge target 순서대로)
  const childrenMap = {}
  nodes.forEach(n => { childrenMap[n.id] = [] })
  edges.forEach(e => {
    if (childrenMap[e.source] !== undefined) {
      childrenMap[e.source].push(e.target)
    }
  })

  // incoming edge가 없는 노드 = root
  const targetIds = new Set(edges.map(e => e.target))
  const roots = nodes.filter(n => !targetIds.has(n.id))

  if (roots.length === 0) {
    return { yaml: null, error: '루트 노드를 찾을 수 없습니다. (순환 연결 확인)' }
  }
  if (roots.length > 1) {
    return { yaml: null, error: `루트 노드가 ${roots.length}개입니다. 트리는 루트가 1개여야 합니다.` }
  }

  const nodeMap = {}
  nodes.forEach(n => { nodeMap[n.id] = n })

  function buildTree(nodeId) {
    const node = nodeMap[nodeId]
    const { category, name, params, label } = node.data

    const entry = { type: category === 'composites' ? name : (category === 'conditions' ? 'Condition' : 'Action') }

    // composites는 type = Selector/Sequence/Parallel
    // conditions/actions는 type = Condition/Action + name
    if (category !== 'composites') {
      entry.name = name
    }

    if (label && label.trim()) {
      entry.name_label = label.trim()
    }

    if (params && Object.keys(params).length > 0) {
      entry.params = { ...params }
    }

    const children = childrenMap[nodeId]
    if (children && children.length > 0) {
      entry.children = children.map(childId => buildTree(childId))
    }

    return entry
  }

  const tree = buildTree(roots[0].id)

  const doc = {
    name: agentName || 'my_agent',
    version: '1.0.0',
    description: description || '',
    tree,
  }

  try {
    const yamlStr = yaml.dump(doc, { indent: 2, lineWidth: 120, noRefs: true })
    return { yaml: yamlStr, error: null }
  } catch (e) {
    return { yaml: null, error: `YAML 변환 오류: ${e.message}` }
  }
}

export function downloadYaml(yamlStr, filename) {
  const blob = new Blob([yamlStr], { type: 'text/yaml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.yaml') ? filename : `${filename}.yaml`
  a.click()
  URL.revokeObjectURL(url)
}

// ── obs 레퍼런스 주석 (Python 파일 공통 헤더) ──────────────────────
const OBS_REFERENCE_COMMENT = `\
# ── 관측값(obs) 레퍼런스 ──────────────────────────────────────────────
# obs = self._obs()
# obs['ata_deg']           * 180 → ATA 각도 (0=정면, 180=후방)
# obs['aa_deg']            * 180 → 적기가 나를 향하는 각도 (0=정면)
# obs['distance_ft']             → 적기와의 거리 (ft)
# obs['closure_rate_kts']        → 접근 속도 (kts, 양수=가까워짐)
# obs['ego_altitude_ft']         → 내 현재 고도 (ft)
# obs['ego_vc_kts']              → 내 현재 속도 (kts)
# obs['energy_diff_ft']          → 에너지 우위 (ft, 양수=내가 우세)
# obs['alt_gap_ft']              → 고도차 (ft, 양수=적기가 높음)
# obs['enm_in_wez']              → 내 WEZ 안에 적기 있음 (bool)
# obs['energy_advantage']        → 에너지 우위 (bool)
# obs['alt_advantage']           → 고도 우위 (bool)
# obs['side_flag']               → 적기 위치 (-1=왼, 0=정면, 1=오른)
# obs['tc_type']                 → 교전 유형 (0=헤드온, 1=추미, 2=추격)
#
# 행동 출력: self.set_action(alt_idx, hdg_idx, vel_idx)
#   alt_idx: 0=급강하  1=하강  2=수평  3=상승  4=급상승
#   hdg_idx: 0=급좌 ~ 4=직진 ~ 8=급우 (22.5° 단위)
#   vel_idx: 0=급감속  1=감속  2=유지  3=가속  4=급가속
# ─────────────────────────────────────────────────────────────────────
`

function generateActionStub(node) {
  const className = node.name
  const params = (node.params || [])
  const initArgs = params.map(p => {
    const val = p.type === 'string' ? `"${p.default}"` : (p.default ?? 0)
    return `${p.key}=${val}`
  }).join(', ')
  const initArgsStr = initArgs ? `, ${initArgs}` : ''
  const selfAssigns = params.map(p => `        self.${p.key} = ${p.key}`).join('\n')

  return `\
class ${className}(BaseAction):
    """${node.description || `커스텀 Action: ${className}`}"""

    def __init__(self, name="${className}"${initArgsStr}):
        super().__init__(name)
${selfAssigns || '        pass'}

    def update(self):
        obs = self._obs()
        # TODO: 여기에 로직 구현
        # 예: if obs['ata_deg'] * 180 < 30: self.set_action(2, 4, 3)
        self.set_action(2, 4, 2)  # 수평/직진/유지
        return py_trees.common.Status.SUCCESS
`
}

function generateConditionStub(node) {
  const className = node.name
  const params = (node.params || [])
  const initArgs = params.map(p => {
    const val = p.type === 'string' ? `"${p.default}"` : (p.default ?? 0)
    return `${p.key}=${val}`
  }).join(', ')
  const initArgsStr = initArgs ? `, ${initArgs}` : ''
  const selfAssigns = params.map(p => `        self.${p.key} = ${p.key}`).join('\n')

  return `\
class ${className}(_CondBase):
    """${node.description || `커스텀 Condition: ${className}`}"""

    def __init__(self, name="${className}"${initArgsStr}):
        super().__init__(name)
${selfAssigns || '        pass'}

    def update(self):
        obs = self._obs()
        # TODO: 여기에 조건 로직 구현
        # 반환: py_trees.common.Status.SUCCESS (조건 충족) or FAILURE (미충족)
        return py_trees.common.Status.FAILURE
`
}

/**
 * 제출용 ZIP 패키지 생성 및 다운로드
 * 구조: my_agent/my_agent.yaml + my_agent/nodes/__init__.py 등
 */
export async function exportToZip(agentName, description, nodes, edges, customNodes = []) {
  const { yaml: yamlStr, error } = exportToYaml(agentName, description, nodes, edges)
  if (error) return { error }

  const name = agentName || 'my_agent'
  const zip = new JSZip()
  const folder = zip.folder(name)

  folder.file(`${name}.yaml`, yamlStr)

  // 커스텀 노드 분류
  const customActions = customNodes.filter(n => n.category === 'actions')
  const customConditions = customNodes.filter(n => n.category === 'conditions')

  // custom_actions.py
  if (customActions.length > 0) {
    const lines = [
      '# 커스텀 Action 노드 — BT 에디터에서 자동 생성됨',
      'import py_trees',
      'try:',
      '    from .base import BaseAction',
      'except ImportError:',
      '    from src.behavior_tree.nodes.base import BaseAction',
      '',
      OBS_REFERENCE_COMMENT,
      ...customActions.map(n => generateActionStub(n)),
    ]
    folder.file('nodes/custom_actions.py', lines.join('\n'))
  } else {
    folder.file('nodes/custom_actions.py', '# 커스텀 Action 노드 (필요시 여기에 추가)\n')
  }

  // custom_conditions.py
  if (customConditions.length > 0) {
    const lines = [
      '# 커스텀 Condition 노드 — BT 에디터에서 자동 생성됨',
      'import py_trees',
      'try:',
      '    from .base import _CondBase',
      'except ImportError:',
      '    from src.behavior_tree.nodes.base import _CondBase',
      '',
      OBS_REFERENCE_COMMENT,
      ...customConditions.map(n => generateConditionStub(n)),
    ]
    folder.file('nodes/custom_conditions.py', lines.join('\n'))
  } else {
    folder.file('nodes/custom_conditions.py', '# 커스텀 Condition 노드 (필요시 여기에 추가)\n')
  }

  // nodes/__init__.py — 커스텀 노드 import 자동 삽입
  const initLines = ['# BT 에디터에서 자동 생성됨']
  if (customActions.length > 0) {
    const names = customActions.map(n => n.name).join(', ')
    initLines.push(`from .custom_actions import ${names}`)
  }
  if (customConditions.length > 0) {
    const names = customConditions.map(n => n.name).join(', ')
    initLines.push(`from .custom_conditions import ${names}`)
  }
  if (customActions.length === 0 && customConditions.length === 0) {
    initLines.push('# 빌트인 노드만 사용하는 경우 이 파일은 수정 불필요')
  }
  folder.file('nodes/__init__.py', initLines.join('\n') + '\n')

  const blob = await zip.generateAsync({ type: 'blob' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.zip`
  a.click()
  URL.revokeObjectURL(url)
  return { error: null }
}
