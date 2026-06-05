import { useState } from 'react'

const OBS_SECTIONS = [
  {
    title: '각도 값 (×180 = 실제 도수)',
    items: [
      { key: 'ata_deg', desc: '적기 방향각 (0=정면, 1=후방)' },
      { key: 'aa_deg', desc: '적기→나 조준각 (0=정면, 1=후방)' },
      { key: 'tau_deg', desc: '롤 보정 목표 (-1~1)' },
      { key: 'rel_bearing_deg', desc: '상대 베어링 (-1~1)' },
    ],
  },
  {
    title: '비행 데이터',
    items: [
      { key: 'distance_ft', desc: '적기와의 거리 (ft)' },
      { key: 'ego_altitude_ft', desc: '내 고도 (ft)' },
      { key: 'ego_vc_kts', desc: '내 속도 (kts)' },
      { key: 'closure_rate_kts', desc: '접근 속도 (kts, 양수=가까워짐)' },
      { key: 'energy_diff_ft', desc: '에너지 우위 (ft, 양수=내가 우세)' },
      { key: 'alt_gap_ft', desc: '고도차 (ft, 양수=적기가 높음)' },
    ],
  },
  {
    title: '이산 / 불리언',
    items: [
      { key: 'enm_in_wez', desc: '내 WEZ 안에 적기 있음 (bool)' },
      { key: 'energy_advantage', desc: '에너지 우위 (bool)' },
      { key: 'alt_advantage', desc: '고도 우위 (bool)' },
      { key: 'side_flag', desc: '적기 위치 (-1=왼, 0=정면, 1=오른)' },
      { key: 'tc_type', desc: '교전 유형 (0=헤드온, 1=추미, 2=추격)' },
    ],
  },
]

const ACTION_INDICES = [
  {
    name: 'alt_idx',
    label: '고도 조작',
    values: ['0 급강하', '1 하강', '2 수평', '3 상승', '4 급상승'],
  },
  {
    name: 'hdg_idx',
    label: '방향 조작 (22.5° 단위)',
    values: ['0 급좌', '1', '2', '3', '4 직진', '5', '6', '7', '8 급우'],
  },
  {
    name: 'vel_idx',
    label: '속도 조작',
    values: ['0 급감속', '1 감속', '2 유지', '3 가속', '4 급가속'],
  },
]

export default function ObsLegend() {
  const [open, setOpen] = useState(false)

  return (
    <div className="absolute top-3 right-16 z-10">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800/90 hover:bg-gray-700 border border-gray-600 rounded-lg text-xs text-gray-300 shadow-lg transition-colors backdrop-blur-sm"
          title="관측값 레전드 열기"
        >
          <span>📡</span>
          <span className="font-mono font-semibold">obs</span>
        </button>
      ) : (
        <div className="w-72 bg-gray-900/95 border border-gray-600 rounded-lg shadow-2xl backdrop-blur-sm max-h-[80vh] overflow-y-auto">
          {/* 헤더 */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 sticky top-0 bg-gray-900">
            <span className="text-xs font-bold text-gray-200">📡 관측값 레전드</span>
            <button
              onClick={() => setOpen(false)}
              className="text-gray-500 hover:text-gray-300 text-sm leading-none"
            >×</button>
          </div>

          <div className="p-2">
            {/* obs 섹션들 */}
            {OBS_SECTIONS.map(section => (
              <div key={section.title} className="mb-3">
                <div className="text-gray-500 text-xs uppercase tracking-wider mb-1 px-1">{section.title}</div>
                {section.items.map(item => (
                  <div key={item.key} className="flex items-start gap-1.5 py-0.5 px-1 rounded hover:bg-gray-800/50">
                    <code className="text-blue-400 text-xs font-mono shrink-0 w-[130px]">{item.key}</code>
                    <span className="text-gray-400 text-xs leading-relaxed">{item.desc}</span>
                  </div>
                ))}
              </div>
            ))}

            {/* 행동 출력 */}
            <div className="border-t border-gray-700 pt-2 mt-1">
              <div className="text-gray-500 text-xs uppercase tracking-wider mb-1.5 px-1">
                행동 출력: <code className="text-orange-400">set_action(alt, hdg, vel)</code>
              </div>
              {ACTION_INDICES.map(act => (
                <div key={act.name} className="mb-2 px-1">
                  <div className="flex items-center gap-1 mb-0.5">
                    <code className="text-orange-400 text-xs font-mono">{act.name}</code>
                    <span className="text-gray-500 text-xs">— {act.label}</span>
                  </div>
                  <div className="flex flex-wrap gap-1 ml-2">
                    {act.values.map((v, i) => (
                      <span key={i} className="text-gray-400 text-xs font-mono bg-gray-800 rounded px-1 py-0.5">{v}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* 예시 */}
            <div className="border-t border-gray-700 pt-2 mt-1">
              <div className="text-gray-500 text-xs uppercase tracking-wider mb-1 px-1">코드 예시</div>
              <pre className="text-xs text-gray-400 bg-gray-800/80 rounded p-2 font-mono leading-relaxed overflow-x-auto">{`obs = self._obs()
ata = obs['ata_deg'] * 180
dist = obs['distance_ft']

# 수평/직진/유지
self.set_action(2, 4, 2)`}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
