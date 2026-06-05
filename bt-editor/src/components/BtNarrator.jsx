/**
 * BtNarrator.jsx — BT 트리를 도그파이트 시나리오 자연어로 해설
 */
import { useMemo } from 'react'
import manifest from '../data/nodes-manifest.json'

const ALL_DEFS = [
  ...manifest.composites,
  ...manifest.conditions,
  ...manifest.actions,
]
function getDef(name) { return ALL_DEFS.find(n => n.name === name) || null }

/* ─── 트리 빌더 ─── */
function buildTree(nodes, edges) {
  if (!nodes.length) return null
  const childIds = new Set(edges.map(e => e.target))
  const roots = nodes.filter(n => !childIds.has(n.id))
  if (!roots.length) return null

  function build(id) {
    const node = nodes.find(n => n.id === id)
    if (!node) return null
    const children = edges
      .filter(e => e.source === id)
      .sort((a, b) => {
        const x = id => nodes.find(n => n.id === id)?.position?.x ?? 0
        return x(a.target) - x(b.target)
      })
      .map(e => build(e.target))
      .filter(Boolean)
    return { id, data: node.data, type: node.type, children }
  }
  return build(roots[0].id)
}

/* ─── 트리 순회: raw 데이터 보존 ─── */
function collectBranches(node) {
  if (!node) return []
  const items = []

  function walk(n) {
    if (!n) return
    const { data: d, type: t, children: c } = n

    if (t === 'compositeNode') {
      if (d.name === 'Selector' || d.name === 'Parallel') {
        c.forEach(walk)
      } else if (d.name === 'Sequence') {
        const conds = [], acts = []
        function leaves(x) {
          if (!x) return
          if (x.type === 'conditionNode') conds.push({ name: x.data.name, params: x.data.params || {} })
          else if (x.type === 'actionNode') acts.push({ name: x.data.name, params: x.data.params || {} })
          else x.children?.forEach(leaves)
        }
        c.forEach(leaves)
        if (conds.length || acts.length) items.push({ conditions: conds, actions: acts })
      }
    } else if (t === 'conditionNode') {
      items.push({ conditions: [{ name: d.name, params: d.params || {} }], actions: [] })
    } else if (t === 'actionNode') {
      items.push({ conditions: [], actions: [{ name: d.name, params: d.params || {} }] })
    }
  }

  walk(node)
  return items
}

/* ─── 전술 해설 생성 (패턴 매칭) ─── */
function generateNarrative(conditions, actions) {
  const cn = conditions.map(c => c.name)
  const an = actions.map(a => a.name)

  // ── 생존 패턴 ──
  if (cn.includes('BelowHardDeck')) {
    const climbAct = actions.find(a => ['ClimbTo', 'ClimbingTurn'].includes(a.name))
    const alt = climbAct?.params?.target_altitude_ft ?? 3000
    return {
      title: '긴급 탈출 상승',
      story: `Hard Deck(최저 고도)은 이 아래로 내려가면 즉시 격추 판정입니다. 고도를 항상 감시하다가 위험 수준에 가까워지면 다른 모든 행동을 중단하고 ${alt}ft까지 즉시 상승합니다.`,
      urgency: 'critical',
    }
  }

  // ── 적 WEZ 회피 ──
  if (cn.includes('InEnemyWEZ')) {
    return {
      title: '적 사격 즉시 회피',
      story: '적기의 무장 교전 구역(WEZ) 안에 들어온 상태입니다. 적이 지금 당장 나를 격추할 수 있는 각도와 거리에 있다는 뜻이므로, 즉각 회피 기동으로 그 구역에서 벗어납니다.',
      urgency: 'critical',
    }
  }

  // ── 위협/방어 패턴 ──
  if (cn.some(n => ['UnderThreat', 'IsDefensiveSituation'].includes(n))) {
    const defAct = actions.find(a => ['BreakTurn', 'DefensiveManeuver', 'DefensiveSpiral', 'Evade'].includes(a.name))
    const actName = defAct ? (getDef(defAct.name)?.koreanName ?? defAct.name) : '회피 기동'
    return {
      title: '방어 기동 발동',
      story: `적기가 나를 후방에서 추격하거나 조준하고 있습니다. 이대로 두면 격추될 수 있으므로 ${actName}으로 적기의 공격선에서 즉시 벗어납니다.`,
      urgency: 'defensive',
    }
  }

  // ── 오버슈트 방지 ──
  if (cn.includes('IsOvershootRisk') || an.includes('HighYoYo')) {
    return {
      title: '하이 요요 — 오버슈트 방지',
      story: '적기 후방을 추격하는 속도가 너무 빨라 앞으로 지나쳐버릴(오버슈트) 위험이 있습니다. 순간 상승하여 속도를 죽인 뒤 다시 적기 후방에 위치를 잡습니다.',
      urgency: 'normal',
    }
  }

  if (an.includes('LowYoYo')) {
    return {
      title: '로우 요요 — 빠른 추격',
      story: '적기가 멀리 도망가고 있습니다. 하강하여 위치 에너지를 속도로 변환하고, 가속으로 빠르게 거리를 좁혀 다시 공격 위치를 잡습니다.',
      urgency: 'normal',
    }
  }

  // ── Merge / 선회전 분기 ──
  if (cn.some(n => ['IsMerged', 'IsOneCircle', 'IsTwoCircle'].includes(n))) {
    const isOne = cn.includes('IsOneCircle') || an.includes('OneCircleFight')
    const isTwo = cn.includes('IsTwoCircle') || an.includes('TwoCircleFight')
    if (isOne) return {
      title: '1-서클 선회전',
      story: '적기와 같은 방향으로 선회하는 전투입니다. 선회 반경이 작을수록(저속) 유리하므로 코너 속도 이하를 유지하며 적기보다 먼저 후방을 점유합니다.',
      urgency: 'attack',
    }
    if (isTwo) return {
      title: '2-서클 선회전',
      story: '적기와 반대 방향으로 선회하는 전투입니다. 선회율이 높을수록 유리하므로 코너 속도를 유지하며 각속도 경쟁에서 앞서 후방을 점유합니다.',
      urgency: 'attack',
    }
    return {
      title: 'Merge — 방향 선택',
      story: '적기와 교차 통과 직후입니다. 1-서클(동방향) 또는 2-서클(반방향) 중 유리한 전략을 선택하여 후방 점유를 시도합니다.',
      urgency: 'normal',
    }
  }

  // ── 3-9 라인 ──
  if (cn.includes('Is39Line')) {
    return {
      title: '3-9 라인 전환',
      story: '적기와 정확히 측면에 나란한 상태(3-9 라인)입니다. 이 순간 빠르게 방향 전환을 하면 적기 후방을 차지할 수 있는 핵심 타이밍입니다.',
      urgency: 'normal',
    }
  }

  // ── 공격 우위 상황 ──
  if (cn.includes('IsOffensiveSituation')) {
    return {
      title: '공격 우위 — OBFM 시작',
      story: '내가 적기의 후방에 위치한 공격 우위 상황입니다. 이 기회를 최대한 활용하여 총 공격 또는 추적 기동으로 빠르게 격추를 시도합니다.',
      urgency: 'attack',
    }
  }

  // ── 정면 교전 ──
  if (cn.includes('IsNeutralSituation')) {
    return {
      title: 'Head-on — 교전 방향 선택',
      story: '서로 정면으로 돌진하는 Head-on 상황입니다. 빠르게 선회 방향을 결정하여 적기보다 먼저 후방을 점유하는 것이 관건입니다.',
      urgency: 'normal',
    }
  }

  // ── 에너지 관련 ──
  if (cn.some(n => ['EnergyHighPs', 'IsEnergyAdvantage', 'SpecificEnergyAbove'].includes(n))) {
    return {
      title: '에너지 우위 활용',
      story: '현재 속도+고도 에너지가 적기보다 높은 상태입니다. 이 에너지 차이를 이용한 기동으로 장기전에서 적기를 소진시키는 전략을 시작합니다.',
      urgency: 'normal',
    }
  }

  // ── 거리 + 총 공격 ──
  if (cn.some(n => ['DistanceBelow', 'EnemyInRange'].includes(n)) && cn.includes('ATABelow') && an.includes('GunAttack')) {
    const distNode = conditions.find(c => ['DistanceBelow', 'EnemyInRange'].includes(c.name))
    const dist = distNode?.params?.threshold_ft ?? distNode?.params?.max_distance_ft ?? 3000
    const ataNode = conditions.find(c => c.name === 'ATABelow')
    const ata = ataNode?.params?.threshold_deg ?? 15
    return {
      title: '총 공격 조건 충족',
      story: `거리 ${dist}ft 이내이면서 기수 각도 ${ata}° 이하(정면 조준)가 동시에 충족된 상태입니다. 이것이 바로 Gun WEZ — 총알이 적기에 닿는 거리와 각도이므로 즉시 공격합니다.`,
      urgency: 'attack',
    }
  }

  // ── 거리 + 추적 패턴 ──
  if (cn.some(n => ['DistanceBelow', 'EnemyInRange'].includes(n))) {
    const distNode = conditions.find(c => ['DistanceBelow', 'EnemyInRange'].includes(c.name))
    const dist = distNode?.params?.threshold_ft ?? distNode?.params?.max_distance_ft ?? 9843
    const pursuitAct = actions.find(a => ['GunAttack', 'LeadPursuit', 'PurePursuit', 'LagPursuit'].includes(a.name))

    if (pursuitAct?.name === 'LagPursuit') return {
      title: '근접 — 지연 추적으로 후방 점유',
      story: `거리가 ${dist}ft 이내로 좁혀졌습니다. 너무 빠르게 추격하면 오버슈트가 날 수 있으므로 Lag Pursuit(지연 추적)으로 적기 뒤쪽을 지향해 속도를 죽이며 후방 위치를 잡습니다.`,
      urgency: 'attack',
    }
    if (pursuitAct?.name === 'LeadPursuit') return {
      title: '근접 — 선행 추적으로 조준',
      story: `거리가 ${dist}ft 이내로 좁혀졌습니다. Lead Pursuit(선행 추적)으로 적기의 진행 방향 앞을 조준하여 충돌점(피탄 예상 위치)에 총구를 겨냥합니다.`,
      urgency: 'attack',
    }
    if (pursuitAct?.name === 'GunAttack') return {
      title: '근접 총 공격',
      story: `거리가 ${dist}ft 이내로 근접한 상태입니다. Gun WEZ 안에 있으므로 즉시 총 공격을 실행합니다.`,
      urgency: 'attack',
    }
    return {
      title: '근접 추적 기동',
      story: `적기가 ${dist}ft 이내로 근접했습니다. 거리가 좁혀진 만큼 더 공격적인 추적 기동으로 전환하여 유리한 위치를 확보합니다.`,
      urgency: 'attack',
    }
  }

  // ── 고도 기동 ──
  if (an.some(n => ['ClimbTo', 'ClimbingTurn'].includes(n))) {
    const climbAct = actions.find(a => ['ClimbTo', 'ClimbingTurn'].includes(a.name))
    const alt = climbAct?.params?.target_altitude_ft ?? 10000
    return {
      title: '고도 확보 기동',
      story: `${alt}ft까지 상승하여 위치 에너지를 확보합니다. 높은 고도는 잠재적 에너지(속도로 전환 가능)이므로 장기전에서 유리한 위치가 됩니다.`,
      urgency: 'normal',
    }
  }

  if (an.some(n => ['DescendTo', 'DescendingTurn'].includes(n))) {
    return {
      title: '하강 — 속도 변환',
      story: '고도를 낮추며 위치 에너지를 속도로 변환합니다. 하강 시 가속이 붙어 빠른 추격이나 공격에 유리합니다.',
      urgency: 'normal',
    }
  }

  // ── 가속/감속 ──
  if (an.includes('Accelerate')) {
    return {
      title: '가속 — 에너지 충전',
      story: '현재 속도가 낮아 기동 자유도가 부족합니다. 최대 추력으로 가속하여 코너 속도 이상으로 회복시킵니다. 단, 너무 빠르면 선회율이 낮아집니다.',
      urgency: 'normal',
    }
  }

  if (an.includes('Decelerate')) {
    return {
      title: '감속 — 코너 속도 유지',
      story: '속도가 너무 빨라 선회율이 저하되었습니다. 감속하여 최대 선회율 구간(코너 속도)으로 돌아가면 더 빠르게 기수 방향을 전환할 수 있습니다.',
      urgency: 'normal',
    }
  }

  // ── 폴백 추적 (조건 없음) ──
  if (conditions.length === 0 && an.some(n => ['Pursue', 'LeadPursuit', 'PurePursuit', 'LagPursuit'].includes(n))) {
    return {
      title: '기본 추적 (항상 실행)',
      story: '위의 모든 특수 조건이 해당되지 않을 때의 기본 행동입니다. 어떤 상황에서도 멈추지 않고 적기를 추적하며 교전 기회를 만들어 갑니다.',
      urgency: 'normal',
    }
  }

  // ── 기본 폴백 ──
  if (conditions.length === 0) {
    const actName = actions.length ? (getDef(an[0])?.koreanName ?? an[0]) : '대기'
    return {
      title: `기본 행동 — ${actName}`,
      story: `특정 조건 없이 항상 실행되는 행동입니다: ${actName}.`,
      urgency: 'normal',
    }
  }

  // ── 제네릭 ──
  const condNames = conditions.map(c => getDef(c.name)?.koreanName ?? c.name).join(' + ')
  const actNames = actions.map(a => getDef(a.name)?.koreanName ?? a.name).join(', ')
  return {
    title: actNames || condNames || '분기',
    story: conditions.length && actions.length
      ? `${condNames} 조건이 충족되면 ${actNames}을(를) 실행합니다.`
      : conditions.length
      ? `${condNames} 여부를 확인합니다.`
      : `${actNames}을(를) 실행합니다.`,
    urgency: 'normal',
  }
}

/* ─── 긴급도 ─── */
function urgency(conditions, actions) {
  const cn = conditions.map(c => c.name)
  const an = actions.map(a => a.name)
  if (cn.includes('BelowHardDeck') || cn.includes('InEnemyWEZ')) return 'critical'
  if (cn.some(n => ['UnderThreat', 'IsDefensiveSituation'].includes(n)) ||
      an.some(n => ['BreakTurn', 'DefensiveManeuver', 'DefensiveSpiral', 'Evade'].includes(n))) return 'defensive'
  if (an.some(n => ['GunAttack', 'LeadPursuit', 'PurePursuit', 'LagPursuit'].includes(n)) ||
      cn.some(n => ['IsOffensiveSituation', 'ATABelow'].includes(n))) return 'attack'
  return 'normal'
}

/* ─── 전체 요약 생성 ─── */
function generateOverallSummary(branches) {
  if (!branches.length) return null
  const parts = []
  if (branches.some(b => b.narrative.title.includes('탈출') || b.narrative.title.includes('Hard Deck')))
    parts.push('생존 최우선')
  if (branches.some(b => b.urgency === 'critical' && !b.narrative.title.includes('탈출')))
    parts.push('즉각 회피')
  if (branches.some(b => b.urgency === 'defensive')) parts.push('위협 시 방어')
  if (branches.some(b => b.urgency === 'attack')) parts.push('공격 기회 포착')
  if (branches.some(b => b.narrative.title.includes('폴백') || b.narrative.title.includes('항상 실행')))
    parts.push('기본 추적 유지')
  return parts.length ? parts.join(' → ') : '우선순위 순 행동'
}

/* ─── 종합 평가 ─── */
function evaluate(nodes) {
  const names = nodes.map(n => n.data?.name ?? '')
  return {
    hardDeck: names.includes('BelowHardDeck') && names.some(n => ['ClimbTo', 'ClimbingTurn'].includes(n)),
    attack:   names.some(n => ['GunAttack', 'LeadPursuit', 'PurePursuit', 'LagPursuit'].includes(n)),
    defense:  names.some(n => ['BreakTurn', 'DefensiveManeuver', 'DefensiveSpiral', 'Evade'].includes(n)),
    pursuit:  names.some(n => ['Pursue', 'LeadPursuit', 'PurePursuit', 'LagPursuit'].includes(n)),
  }
}

/* ─── UI ─── */
const STYLE = {
  critical:  { border: 'border-red-700',    badge: 'bg-red-900/80 text-red-200',       dot: 'bg-red-500',    label: '긴급' },
  defensive: { border: 'border-yellow-700', badge: 'bg-yellow-900/80 text-yellow-200', dot: 'bg-yellow-400', label: '방어' },
  attack:    { border: 'border-green-700',  badge: 'bg-green-900/80 text-green-200',   dot: 'bg-green-400',  label: '공격' },
  normal:    { border: 'border-gray-700',   badge: 'bg-gray-800 text-gray-400',        dot: 'bg-gray-500',   label: '일반' },
}

function BranchCard({ branch }) {
  const s = STYLE[branch.urgency]
  const { title, story } = branch.narrative
  return (
    <div className={`shrink-0 w-52 rounded border ${s.border} bg-gray-800/50 p-2 flex flex-col gap-1.5 overflow-y-auto`}>
      {/* 배지 + 타이틀 */}
      <div className="flex items-start gap-1.5">
        <span className={`shrink-0 text-xs font-bold px-1.5 py-0.5 rounded ${s.badge}`}>{branch.priority}순위</span>
        <span className="flex items-center gap-1 text-xs text-gray-300 font-semibold leading-tight">
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot} shrink-0 mt-0.5`} />
          {title}
        </span>
      </div>

      {/* 전술 해설 */}
      <p className="text-gray-400 text-xs leading-relaxed">{story}</p>

      {/* 조건/행동 태그 */}
      {(branch.conditions.length > 0 || branch.actions.length > 0) && (
        <div className="border-t border-gray-700 pt-1.5 flex flex-col gap-0.5">
          {branch.conditions.map((c, i) => (
            <div key={i} className="text-blue-400 text-xs">
              IF · {getDef(c.name)?.koreanName ?? c.name}
            </div>
          ))}
          {branch.actions.map((a, i) => (
            <div key={i} className="text-orange-400 text-xs">
              DO · {getDef(a.name)?.koreanName ?? a.name}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EvalRow({ ok, label }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className={ok ? 'text-green-400' : 'text-red-500'}>{ok ? '✓' : '✗'}</span>
      <span className={ok ? 'text-gray-300' : 'text-gray-500'}>{label}</span>
    </div>
  )
}

/* ─── 메인 컴포넌트 ─── */
export default function BtNarrator({ nodes, edges }) {
  const { branches, ev, summary, rootCount } = useMemo(() => {
    if (!nodes.length) return { branches: [], ev: null, summary: null, rootCount: 0 }
    const childIds = new Set(edges.map(e => e.target))
    const rootCount = nodes.filter(n => !childIds.has(n.id)).length
    const tree = buildTree(nodes, edges)
    const raw = collectBranches(tree)
    const branches = raw.map((item, i) => ({
      priority: i + 1,
      urgency: urgency(item.conditions, item.actions),
      narrative: generateNarrative(item.conditions, item.actions),
      conditions: item.conditions,
      actions: item.actions,
    }))
    return {
      branches,
      ev: evaluate(nodes),
      summary: generateOverallSummary(branches),
      rootCount,
    }
  }, [nodes, edges])

  return (
    <div className="h-full bg-gray-900 border-t border-gray-700 flex overflow-hidden">
      {/* 타이틀 + 전체 요약 */}
      <div className="w-36 shrink-0 border-r border-gray-700 px-3 py-2 flex flex-col justify-center gap-1">
        <div className="text-white text-xs font-bold">전투 행동 해설</div>
        {summary && (
          <div className="text-gray-400 text-xs leading-relaxed mt-1">{summary}</div>
        )}
      </div>

      {/* 브랜치 카드 가로 스크롤 */}
      <div className="flex-1 overflow-x-auto overflow-y-hidden flex gap-2 p-2 items-stretch">
        {!nodes.length ? (
          <div className="flex items-center text-gray-600 text-xs px-2">노드를 배치하면 해설이 표시됩니다</div>
        ) : rootCount > 1 ? (
          <div className="flex items-center text-yellow-400 text-xs px-2">⚠ 루트 노드가 {rootCount}개 — 하나의 트리로 연결하세요</div>
        ) : branches.length === 0 ? (
          <div className="flex items-center text-gray-600 text-xs px-2">연결된 분기가 없습니다</div>
        ) : (
          branches.map((b, i) => <BranchCard key={i} branch={b} />)
        )}
      </div>

      {/* 종합 평가 */}
      {ev && (
        <div className="w-28 shrink-0 border-l border-gray-700 px-3 py-2 flex flex-col justify-center gap-1">
          <div className="text-gray-500 text-xs mb-0.5">종합 평가</div>
          <EvalRow ok={ev.hardDeck} label="Hard Deck" />
          <EvalRow ok={ev.pursuit}  label="추적 기동" />
          <EvalRow ok={ev.attack}   label="공격 분기" />
          <EvalRow ok={ev.defense}  label="방어 기동" />
        </div>
      )}
    </div>
  )
}
