import { useMemo } from 'react'

export function useValidation(nodes, edges) {
  return useMemo(() => {
    if (nodes.length === 0) return []

    const warnings = []
    const nodeNames = new Set(nodes.map(n => n.data?.name))
    const targetIds = new Set(edges.map(e => e.target))
    const sourceIds = new Set(edges.map(e => e.source))

    // 루트 수 확인
    const roots = nodes.filter(n => !targetIds.has(n.id))
    if (roots.length > 1) {
      warnings.push({
        level: 'error',
        msg: `루트 노드가 ${roots.length}개입니다. 트리는 루트가 1개여야 합니다.`,
      })
    }

    // 고립된 노드 (연결 안 됨)
    const isolated = nodes.filter(n => !targetIds.has(n.id) && !sourceIds.has(n.id) && nodes.length > 1)
    if (isolated.length > 0) {
      warnings.push({
        level: 'warning',
        msg: `연결되지 않은 노드 ${isolated.length}개 — "${isolated[0].data?.name}" 등`,
      })
    }

    // Hard Deck 회피 없음
    const hasHardDeck = nodeNames.has('BelowHardDeck')
    const hasClimbTo = nodeNames.has('ClimbTo')
    if (!hasHardDeck || !hasClimbTo) {
      warnings.push({
        level: 'error',
        msg: '⚠️ Hard Deck 회피 없음 — BelowHardDeck + ClimbTo Sequence가 없으면 즉시 패배합니다.',
      })
    }

    // 공격 수단 없음
    const ATTACK_NODES = ['GunAttack', 'Pursue', 'LeadPursuit', 'PurePursuit', 'LagPursuit']
    const hasAttack = ATTACK_NODES.some(n => nodeNames.has(n))
    if (!hasAttack) {
      warnings.push({
        level: 'warning',
        msg: '공격 노드 없음 — Pursue 또는 GunAttack이 없으면 절대 이길 수 없습니다.',
      })
    }

    return warnings
  }, [nodes, edges])
}

const LEVEL_STYLE = {
  error:   'bg-red-900/80 border-red-600 text-red-200',
  warning: 'bg-yellow-900/70 border-yellow-600 text-yellow-200',
}

const LEVEL_ICON = { error: '🔴', warning: '🟡' }

export default function ValidationPanel({ warnings }) {
  if (warnings.length === 0) return null

  return (
    <div className="absolute top-2 left-1/2 -translate-x-1/2 z-20 flex flex-col gap-1 w-[520px] max-w-[90%]">
      {warnings.map((w, i) => (
        <div
          key={i}
          className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium shadow-lg backdrop-blur-sm ${LEVEL_STYLE[w.level]}`}
        >
          <span>{LEVEL_ICON[w.level]}</span>
          <span className="flex-1">{w.msg}</span>
        </div>
      ))}
    </div>
  )
}
