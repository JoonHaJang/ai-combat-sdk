/**
 * TacticalDiagram.jsx
 * 각 BT 노드의 전술 개념을 SVG로 시각화.
 * 파란 삼각형 = 나(플레이어), 빨간 삼각형 = 적기
 */

const W = 120, H = 88
const US   = '#60a5fa'   // 파랑 = 나
const ENM  = '#f87171'   // 빨강 = 적기
const LINE = '#6b7280'   // 선/화살표
const GRN  = '#4ade80'   // 초록 = 좋음
const YLW  = '#fbbf24'   // 노랑 = 기준/경고
const TXT  = '#9ca3af'   // 설명 텍스트

// 항공기 삼각형 (기본 방향 = 위쪽/북쪽, angle로 회전)
function AC({ x, y, angle = 0, color = US, size = 9, opacity = 1 }) {
  const s = size
  const pts = `0,${-s} ${s * 0.65},${s * 0.5} 0,${s * 0.1} ${-s * 0.65},${s * 0.5}`
  return (
    <polygon
      points={pts}
      fill={color}
      stroke="rgba(255,255,255,0.25)"
      strokeWidth="0.5"
      opacity={opacity}
      transform={`translate(${x},${y}) rotate(${angle})`}
    />
  )
}

// 화살표 (시작→끝, 끝에 삼각형 화살촉)
function Arrow({ x1, y1, x2, y2, color = LINE, dashed = false, width = 1.5 }) {
  const dx = x2 - x1, dy = y2 - y1
  const len = Math.sqrt(dx * dx + dy * dy)
  if (len < 2) return null
  const ux = dx / len, uy = dy / len
  const px = -uy * 3, py = ux * 3
  const ax = x2 - ux * 7, ay = y2 - uy * 7

  return (
    <g>
      <line x1={x1} y1={y1} x2={ax} y2={ay}
        stroke={color} strokeWidth={width}
        strokeDasharray={dashed ? '3,2' : undefined}
      />
      <polygon
        points={`${x2},${y2} ${ax + px},${ay + py} ${ax - px},${ay - py}`}
        fill={color}
      />
    </g>
  )
}

// 수평 기준선
function AltLine({ y, color = YLW, label = '' }) {
  return (
    <>
      <line x1="12" y1={y} x2={W - 12} y2={y}
        stroke={color} strokeWidth="1.5" strokeDasharray="4,3" />
      {label && <text x={W - 13} y={y - 3} fill={color} fontSize="7" textAnchor="end">{label}</text>}
    </>
  )
}

// 간단한 레이블 텍스트 (하단 중앙)
function Caption({ text, color = TXT }) {
  return <text x={W / 2} y={H - 3} fill={color} fontSize="7.5" textAnchor="middle">{text}</text>
}

// ──────────────────────────────────────────────
// 조건 노드 다이어그램
// ──────────────────────────────────────────────

function HardDeckDiagram() {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 지면 */}
      <rect x="0" y="74" width={W} height="14" fill="#1f2937" />
      <line x1="0" y1="74" x2={W} y2="74" stroke="#4b5563" strokeWidth="1" />
      <text x="5" y="83" fill="#6b7280" fontSize="7">지면</text>
      {/* Hard Deck 선 */}
      <AltLine y={52} color="#ef4444" label="Hard Deck 1000ft" />
      {/* 위험 구역 */}
      <rect x="0" y="52" width={W} height="22" fill="rgba(239,68,68,0.08)" />
      <text x="8" y="66" fill="#ef4444" fontSize="7">즉시 패배!</text>
      {/* 안전 구역 */}
      <rect x="0" y="0" width={W} height="52" fill="rgba(74,222,128,0.04)" />
      {/* 항공기 */}
      <AC x={W / 2} y={33} color={US} />
      <text x={W / 2 + 13} y={36} fill={US} fontSize="7">안전</text>
      <Caption text="이 선 아래 = 즉시 패배" color="#ef4444" />
    </svg>
  )
}

function ATADiagram({ below = true }) {
  // 나: 아래 중앙, 적기: 위쪽 오른편 (ATA ≠ 0)
  const ux = 55, uy = 72
  const ex = 88, ey = 18

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 기수 방향선 (위쪽) */}
      <line x1={ux} y1={uy} x2={ux} y2={uy - 30}
        stroke={US} strokeWidth="1" strokeDasharray="2,2" opacity="0.5" />
      {/* 적기 방향선 */}
      <line x1={ux} y1={uy} x2={ex - 4} y2={ey + 4}
        stroke={LINE} strokeWidth="1" strokeDasharray="3,2" />
      {/* ATA 각도 호 */}
      <path
        d={`M ${ux} ${uy - 22} A 22 22 0 0 1 ${ux + 15} ${uy - 17}`}
        stroke={YLW} strokeWidth="1.5" fill="none"
      />
      <text x={ux + 8} y={uy - 24} fill={YLW} fontSize="7">ATA</text>
      {/* 항공기 */}
      <AC x={ux} y={uy} color={US} />
      <AC x={ex} y={ey} color={ENM} angle={90} size={8} />
      <text x={ex + 5} y={ey + 10} fill={ENM} fontSize="7">적기</text>
      <text x={ux - 18} y={uy + 4} fill={US} fontSize="7">나</text>
      <Caption text={below ? 'ATA 작을수록 정면 근접 → 조준 가능' : 'ATA 클수록 측/후방 위치'} />
    </svg>
  )
}

function DistanceDiagram({ below = true }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AC x={20} y={H / 2 - 2} color={US} angle={90} />
      <AC x={100} y={H / 2 - 2} color={ENM} angle={-90} />
      {/* 거리 화살표 */}
      <line x1={27} y1={H / 2 - 14} x2={93} y2={H / 2 - 14}
        stroke={YLW} strokeWidth="1.2" />
      <line x1={27} y1={H / 2 - 11} x2={27} y2={H / 2 - 17} stroke={YLW} strokeWidth="1.2" />
      <line x1={93} y1={H / 2 - 11} x2={93} y2={H / 2 - 17} stroke={YLW} strokeWidth="1.2" />
      <text x={60} y={H / 2 - 16} fill={YLW} fontSize="7.5" textAnchor="middle">
        {below ? '< 임계값' : '> 임계값'}
      </text>
      <text x={20} y={H / 2 + 17} fill={US} fontSize="7" textAnchor="middle">나</text>
      <text x={100} y={H / 2 + 17} fill={ENM} fontSize="7" textAnchor="middle">적기</text>
      <Caption text={below ? '지정 거리 이내 → SUCCESS' : '지정 거리 이상 → SUCCESS'} />
    </svg>
  )
}

function ThreatDiagram({ isWEZ = false }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 적기 (아래를 향함) */}
      <AC x={W / 2} y={16} color={ENM} angle={180} />
      {/* WEZ / 위협 콘 */}
      <polygon
        points={`${W / 2},26 ${W / 2 - 24},62 ${W / 2 + 24},62`}
        fill="rgba(239,68,68,0.12)"
        stroke="#ef4444"
        strokeWidth="1"
        strokeDasharray="2,2"
      />
      {/* 나 (콘 내부) */}
      <AC x={W / 2} y={52} color={US} />
      <text x={W / 2 + 5} y={16} fill={ENM} fontSize="7">적기</text>
      <text x={W / 2 + 13} y={54} fill="#ef4444" fontSize="7">나 ⚠</text>
      <Caption text={isWEZ ? '적 WEZ 내 위치 → 즉각 회피!' : '적기 AA 큼 → 내가 겨냥당함'} color="#ef4444" />
    </svg>
  )
}

function SituationDiagram({ type }) {
  if (type === 'offensive') {
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
        <AC x={W / 2} y={18} color={ENM} angle={0} />
        <AC x={W / 2} y={60} color={US} angle={0} />
        <Arrow x1={W / 2} y1={53} x2={W / 2} y2={28} color={GRN} />
        <text x={W / 2 + 13} y={20} fill={ENM} fontSize="7">적기</text>
        <text x={W / 2 + 13} y={63} fill={US} fontSize="7">나 (후방)</text>
        <Caption text="✓ 공격 우위 — OBFM 기동 시작" color={GRN} />
      </svg>
    )
  }
  if (type === 'defensive') {
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
        <AC x={W / 2} y={18} color={US} angle={0} />
        <AC x={W / 2} y={60} color={ENM} angle={0} />
        <Arrow x1={W / 2} y1={53} x2={W / 2} y2={28} color="#ef4444" />
        <text x={W / 2 + 13} y={20} fill={US} fontSize="7">나 (전방)</text>
        <text x={W / 2 + 13} y={63} fill={ENM} fontSize="7">적기 (추격)</text>
        <Caption text="⚠ 즉각 회피 기동 필요" color="#ef4444" />
      </svg>
    )
  }
  // neutral head-on
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AC x={36} y={32} color={US} angle={135} />
      <AC x={84} y={32} color={ENM} angle={-135} />
      <Arrow x1={42} y1={38} x2={60} y2={55} color={US} dashed />
      <Arrow x1={78} y1={38} x2={60} y2={55} color={ENM} dashed />
      <text x={60} y={62} fill={YLW} fontSize="7" textAnchor="middle">정면 교차</text>
      <Caption text="Head-on → 1/2 circle 전략 선택" />
    </svg>
  )
}

function AltitudeDiagram({ above = true }) {
  const thY = 44
  const acY = above ? 24 : 62
  const color = above ? GRN : YLW
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AltLine y={thY} color={color} label="기준 고도" />
      <rect x="0" y={above ? 0 : thY} width={W} height={above ? thY : H - thY - 8}
        fill={`${color}08`} />
      <text x="8" y={above ? 20 : 62} fill={color} fontSize="7">SUCCESS 구역</text>
      <AC x={W / 2} y={acY} color={US} />
      <Caption text={above ? '이 고도 위 → SUCCESS' : '이 고도 아래 → SUCCESS'} color={color} />
    </svg>
  )
}

function EnergyDiagram() {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 내 에너지 바 */}
      <rect x="18" y="18" width="28" height="50" fill="#1e3a5f" stroke="#374151" strokeWidth="1" />
      <rect x="18" y="22" width="28" height="46" fill={US} opacity="0.75" />
      <text x="32" y="78" fill={US} fontSize="7" textAnchor="middle">나</text>
      {/* 적 에너지 바 */}
      <rect x="54" y="18" width="28" height="50" fill="#3f1515" stroke="#374151" strokeWidth="1" />
      <rect x="54" y="36" width="28" height="32" fill={ENM} opacity="0.75" />
      <text x="68" y="78" fill={ENM} fontSize="7" textAnchor="middle">적기</text>
      {/* 우위 표시 */}
      <text x="100" y="38" fill={GRN} fontSize="11" textAnchor="middle">↑</text>
      <text x="100" y="50" fill={GRN} fontSize="7" textAnchor="middle">우위</text>
      <Caption text="에너지 = 속도 + 고도 합산" />
    </svg>
  )
}

function MergedDiagram() {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <Arrow x1={28} y1={58} x2={85} y2={26} color={US} />
      <Arrow x1={92} y1={30} x2={35} y2={62} color={ENM} />
      <AC x={38} y={60} color={US} angle={-50} />
      <AC x={82} y={28} color={ENM} angle={130} />
      <text x={60} y={44} fill={YLW} fontSize="8" textAnchor="middle">교차!</text>
      <Caption text="Merge — 방향 전환의 핵심 순간" />
    </svg>
  )
}

function Line39Diagram() {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AC x={W / 2} y={H / 2 - 2} color={ENM} angle={0} size={9} />
      {/* 3-9 라인 */}
      <line x1="8" y1={H / 2} x2={W - 8} y2={H / 2}
        stroke={YLW} strokeWidth="1.5" strokeDasharray="4,3" />
      <text x="10" y={H / 2 - 3} fill={YLW} fontSize="8">9</text>
      <text x={W - 14} y={H / 2 - 3} fill={YLW} fontSize="8">3</text>
      {/* 나: 3시 방향 */}
      <AC x={W - 22} y={H / 2} color={US} angle={-90} size={8} />
      <text x={W - 22} y={H / 2 + 15} fill={US} fontSize="7" textAnchor="middle">나 (3시)</text>
      <Caption text="3-9 라인 = 정확히 측면" />
    </svg>
  )
}

function CircleFightDiagram({ oneCircle = true }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {oneCircle ? (
        <>
          {/* 같은 방향 선회 */}
          <path d="M 30 44 Q 30 10 60 8 Q 90 6 92 38 Q 94 66 70 72 Q 46 78 30 58"
            stroke={US} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
          <path d="M 90 44 Q 80 16 60 14 Q 38 12 30 38"
            stroke={ENM} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
          <AC x={30} y={44} color={US} angle={0} />
          <AC x={90} y={44} color={ENM} angle={180} />
          <text x={60} y={58} fill={YLW} fontSize="7" textAnchor="middle">← 동방향 →</text>
        </>
      ) : (
        <>
          {/* 반대 방향 선회 */}
          <path d="M 25 44 Q 18 20 38 12 Q 58 4 68 28"
            stroke={US} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
          <path d="M 95 44 Q 102 20 82 12 Q 62 4 52 28"
            stroke={ENM} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
          <AC x={25} y={44} color={US} angle={-30} />
          <AC x={95} y={44} color={ENM} angle={30} />
          <text x={60} y={62} fill={YLW} fontSize="7" textAnchor="middle">→ 반방향 ←</text>
        </>
      )}
      <Caption text={oneCircle ? '반경 싸움 — 저속이 유리' : '선회율 싸움 — 코너 속도 유지'} />
    </svg>
  )
}

// ──────────────────────────────────────────────
// 액션 노드 다이어그램
// ──────────────────────────────────────────────

function PursuitDiagram({ type = 'pure' }) {
  // 적기: 오른쪽 이동 중 (위쪽), 나: 왼쪽 아래
  const ex = 82, ey = 22  // 적기 현재 위치
  const ux = 28, uy = 66  // 나

  // 조준점: lead=앞, pure=현재, lag=뒤
  const aimX = type === 'lead' ? ex + 20 : type === 'pure' ? ex : ex - 18
  const aimY = ey + (type === 'lead' ? 0 : type === 'pure' ? 0 : 3)
  const label = type === 'lead' ? '앞쪽 선제 조준' : type === 'pure' ? '적기 직접 추적' : '뒤쪽 지연 추적'

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 적기 이동 */}
      <AC x={ex} y={ey} color={ENM} angle={90} />
      <Arrow x1={ex + 6} y1={ey} x2={ex + 20} y2={ey} color={ENM} />
      {/* 조준점 */}
      <circle cx={aimX} cy={aimY} r={4} fill="none" stroke={GRN} strokeWidth="1.5" />
      {/* 나 → 조준점 */}
      <line x1={ux} y1={uy} x2={aimX - 3} y2={aimY + 2}
        stroke={US} strokeWidth="1" strokeDasharray="3,2" opacity="0.8" />
      <AC x={ux} y={uy} color={US} angle={-50} />
      <text x={ux - 5} y={uy + 14} fill={US} fontSize="7">나</text>
      <text x={ex - 2} y={ey + 14} fill={ENM} fontSize="7">적기</text>
      <Caption text={label} />
    </svg>
  )
}

function GunAttackDiagram() {
  const ux = W / 2, uy = 74
  const ex = W / 2, ey = 16

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AC x={ux} y={uy} color={US} />
      <AC x={ex} y={ey} color={ENM} />
      {/* Gun WEZ 콘 */}
      <polygon
        points={`${ux},${uy - 11} ${ux - 11},${ey + 10} ${ux + 11},${ey + 10}`}
        fill="rgba(74,222,128,0.18)"
        stroke={GRN}
        strokeWidth="1"
      />
      {/* 거리 표시 */}
      <text x={ux + 14} y={(uy + ey) / 2 + 2} fill={YLW} fontSize="7">500~</text>
      <text x={ux + 14} y={(uy + ey) / 2 + 11} fill={YLW} fontSize="7">3000ft</text>
      <Caption text="WEZ 내 + ATA 15° → 데미지!" color={GRN} />
    </svg>
  )
}

function BreakTurnDiagram() {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 적기: 오른쪽에서 오는 중 */}
      <AC x={96} y={36} color={ENM} angle={-90} size={8} />
      <Arrow x1={89} y1={36} x2={73} y2={36} color={ENM} />
      {/* 나: 급선회 경로 */}
      <AC x={55} y={48} color={US} angle={-30} />
      <path d="M 50 44 Q 18 44 12 22 Q 8 8 28 6"
        stroke={US} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
      <AC x={28} y={7} color={US} angle={90} size={7} opacity="0.5" />
      <text x={14} y={20} fill={US} fontSize="7">회피 완료</text>
      <Caption text="최대 G 급선회 — 최강 방어 기동" />
    </svg>
  )
}

function YoYoDiagram({ high = true }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 적기: 오른쪽 이동 */}
      <AC x={88} y={42} color={ENM} angle={90} size={8} />
      <Arrow x1={81} y1={42} x2={110} y2={42} color={ENM} />
      {/* 나: 시작 위치 */}
      <AC x={24} y={high ? 55 : 42} color={US} angle={90} size={8} />
      {/* 경로 */}
      {high
        ? <path d="M 31 51 Q 55 12 88 34" stroke={US} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
        : <path d="M 31 46 Q 55 76 88 50" stroke={US} strokeWidth="1.5" fill="none" strokeDasharray="3,2" />
      }
      {/* 최종 위치 */}
      <AC x={88} y={high ? 34 : 50} color={US} angle={90} size={7} opacity="0.55" />
      <text x={55} y={high ? 16 : 80} fill={YLW} fontSize="7" textAnchor="middle">
        {high ? '① 상승' : '① 하강 가속'}
      </text>
      <text x={90} y={high ? 26 : 42} fill={GRN} fontSize="7">{high ? '② 후방 재점령' : '② 따라잡기'}</text>
      <Caption text={high ? '오버슈트 방지 + 후방 유지' : '속도 증가로 거리 좁히기'} />
    </svg>
  )
}

function ClimbDescendDiagram({ up = true }) {
  const color = up ? GRN : YLW
  const acY = up ? 62 : 24
  const arrowY2 = up ? 22 : 64

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AltLine y={up ? 24 : 62} color={color} label="목표 고도" />
      <AC x={W / 2} y={acY} color={US} angle={up ? 0 : 180} />
      <Arrow x1={W / 2} y1={acY + (up ? -12 : 12)} x2={W / 2} y2={arrowY2 + (up ? 8 : -8)} color={color} />
      <Caption text={up ? '목표 고도까지 상승' : '목표 고도까지 하강'} color={color} />
    </svg>
  )
}

function AccelerateDiagram({ decel = false }) {
  const color = decel ? YLW : GRN
  const acX = decel ? 72 : 48

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <AC x={acX} y={H / 2} color={US} angle={90} />
      {/* 속도선 */}
      {[28, 40, 52].map((y, i) => (
        decel
          ? <line key={i} x1={16 + i * 4} y1={y} x2={58} y2={y} stroke={color} strokeWidth={1.5 - i * 0.3} />
          : <line key={i} x1={62} y1={y} x2={104 - i * 4} y2={y} stroke={color} strokeWidth={1.5 - i * 0.3} />
      ))}
      <text x={decel ? 8 : 106} y={40} fill={color} fontSize="11" textAnchor="middle">
        {decel ? '◀' : '▶'}
      </text>
      <Caption text={decel ? '감속 → 코너 속도 유지' : '가속 → 에너지 충전'} color={color} />
    </svg>
  )
}

// ──────────────────────────────────────────────
// 외부 API: diagramType → 컴포넌트 맵
// ──────────────────────────────────────────────

const DIAGRAM_MAP = {
  hard_deck:      HardDeckDiagram,
  ata_below:      () => <ATADiagram below={true} />,
  ata_above:      () => <ATADiagram below={false} />,
  distance_below: () => <DistanceDiagram below={true} />,
  distance_above: () => <DistanceDiagram below={false} />,
  threat:         () => <ThreatDiagram isWEZ={false} />,
  enemy_wez:      () => <ThreatDiagram isWEZ={true} />,
  offensive:      () => <SituationDiagram type="offensive" />,
  defensive:      () => <SituationDiagram type="defensive" />,
  neutral:        () => <SituationDiagram type="neutral" />,
  alt_above:      () => <AltitudeDiagram above={true} />,
  alt_below:      () => <AltitudeDiagram above={false} />,
  energy:         EnergyDiagram,
  merged:         MergedDiagram,
  line_39:        Line39Diagram,
  one_circle:     () => <CircleFightDiagram oneCircle={true} />,
  two_circle:     () => <CircleFightDiagram oneCircle={false} />,
  // Actions
  pursue:         () => <PursuitDiagram type="pure" />,
  lead_pursuit:   () => <PursuitDiagram type="lead" />,
  lag_pursuit:    () => <PursuitDiagram type="lag" />,
  gun_attack:     GunAttackDiagram,
  break_turn:     BreakTurnDiagram,
  high_yo_yo:     () => <YoYoDiagram high={true} />,
  low_yo_yo:      () => <YoYoDiagram high={false} />,
  climb:          () => <ClimbDescendDiagram up={true} />,
  descend:        () => <ClimbDescendDiagram up={false} />,
  accelerate:     () => <AccelerateDiagram decel={false} />,
  decelerate:     () => <AccelerateDiagram decel={true} />,
}

export default function TacticalDiagram({ type }) {
  const DiagComp = type ? DIAGRAM_MAP[type] : null
  if (!DiagComp) return null

  return (
    <div className="w-full h-20 rounded border border-gray-700 bg-gray-950 overflow-hidden mb-2">
      <DiagComp />
    </div>
  )
}
