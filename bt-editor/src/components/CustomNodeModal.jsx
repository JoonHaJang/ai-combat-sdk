import { useState } from 'react'

const PARAM_TYPES = ['number', 'string', 'select']

function newParam() {
  return { key: '', type: 'number', default: '', unit: '', description: '' }
}

export default function CustomNodeModal({ onSave, onClose }) {
  const [name, setName] = useState('')
  const [category, setCategory] = useState('actions')
  const [description, setDescription] = useState('')
  const [params, setParams] = useState([])
  const [error, setError] = useState('')

  function handleAddParam() {
    setParams(ps => [...ps, newParam()])
  }

  function handleRemoveParam(i) {
    setParams(ps => ps.filter((_, idx) => idx !== i))
  }

  function handleParamChange(i, field, value) {
    setParams(ps => ps.map((p, idx) => idx === i ? { ...p, [field]: value } : p))
  }

  function handleSave() {
    const trimmed = name.trim()
    if (!trimmed) { setError('노드 이름을 입력하세요.'); return }
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(trimmed)) {
      setError('노드 이름은 영문자로 시작하고, 영문/숫자/밑줄만 사용 가능합니다.')
      return
    }
    // validate params
    for (const p of params) {
      if (!p.key.trim()) { setError('파라미터 key를 모두 입력하세요.'); return }
    }

    const cleanParams = params.map(p => ({
      key: p.key.trim(),
      type: p.type,
      default: p.type === 'number' ? (parseFloat(p.default) || 0) : (p.default || ''),
      unit: p.unit.trim(),
      description: p.description.trim(),
      options: p.type === 'select' ? (p.options || '').split(',').map(s => s.trim()).filter(Boolean) : undefined,
    }))

    onSave({
      id: `custom_${Date.now()}`,
      name: trimmed,
      category,
      description: description.trim(),
      params: cleanParams,
      isCustom: true,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-gray-900 border border-gray-600 rounded-xl shadow-2xl w-[560px] max-h-[90vh] overflow-y-auto">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <h2 className="text-white font-bold text-base">커스텀 노드 추가</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">×</button>
        </div>

        <div className="p-5 space-y-4">
          {/* 이름 + 카테고리 */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs text-gray-400 mb-1">노드 이름 <span className="text-red-400">*</span></label>
              <input
                type="text"
                value={name}
                onChange={e => { setName(e.target.value); setError('') }}
                placeholder="예: MyAttackAction"
                className="w-full bg-gray-800 text-white text-sm px-3 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
              />
            </div>
            <div className="w-36">
              <label className="block text-xs text-gray-400 mb-1">카테고리</label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value)}
                className="w-full bg-gray-800 text-white text-sm px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
              >
                <option value="actions">Action</option>
                <option value="conditions">Condition</option>
              </select>
            </div>
          </div>

          {/* 설명 */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">설명 (선택)</label>
            <input
              type="text"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="이 노드가 하는 일을 간단히 설명하세요"
              className="w-full bg-gray-800 text-white text-sm px-3 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
            />
          </div>

          {/* 파라미터 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs text-gray-400">파라미터</label>
              <button
                onClick={handleAddParam}
                className="text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
              >
                + 추가
              </button>
            </div>

            {params.length === 0 && (
              <p className="text-gray-600 text-xs italic">파라미터가 없습니다. 필요하면 추가하세요.</p>
            )}

            {params.map((p, i) => (
              <div key={i} className="mb-3 p-3 bg-gray-800/60 rounded-lg border border-gray-700">
                <div className="flex gap-2 mb-2">
                  <div className="flex-1">
                    <label className="block text-xs text-gray-500 mb-0.5">key</label>
                    <input
                      type="text"
                      value={p.key}
                      onChange={e => handleParamChange(i, 'key', e.target.value)}
                      placeholder="my_param"
                      className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                    />
                  </div>
                  <div className="w-24">
                    <label className="block text-xs text-gray-500 mb-0.5">타입</label>
                    <select
                      value={p.type}
                      onChange={e => handleParamChange(i, 'type', e.target.value)}
                      className="w-full bg-gray-700 text-white text-xs px-1 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                    >
                      {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                  <div className="w-20">
                    <label className="block text-xs text-gray-500 mb-0.5">기본값</label>
                    <input
                      type="text"
                      value={p.default}
                      onChange={e => handleParamChange(i, 'default', e.target.value)}
                      placeholder="0"
                      className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                    />
                  </div>
                  <div className="w-16">
                    <label className="block text-xs text-gray-500 mb-0.5">단위</label>
                    <input
                      type="text"
                      value={p.unit}
                      onChange={e => handleParamChange(i, 'unit', e.target.value)}
                      placeholder="ft"
                      className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                    />
                  </div>
                  <button
                    onClick={() => handleRemoveParam(i)}
                    className="self-end mb-0.5 text-gray-600 hover:text-red-400 text-sm leading-none"
                  >×</button>
                </div>
                {p.type === 'select' && (
                  <div className="mb-1.5">
                    <label className="block text-xs text-gray-500 mb-0.5">옵션 (쉼표 구분)</label>
                    <input
                      type="text"
                      value={p.options || ''}
                      onChange={e => handleParamChange(i, 'options', e.target.value)}
                      placeholder="optA, optB, optC"
                      className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs text-gray-500 mb-0.5">설명 (선택)</label>
                  <input
                    type="text"
                    value={p.description}
                    onChange={e => handleParamChange(i, 'description', e.target.value)}
                    placeholder="이 파라미터의 역할"
                    className="w-full bg-gray-700 text-white text-xs px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400"
                  />
                </div>
              </div>
            ))}
          </div>

          {/* obs 빠른 참조 */}
          <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
            <div className="text-xs text-gray-500 font-semibold mb-1.5">📡 update() 작성 시 사용 가능한 obs 키</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs font-mono">
              {[
                "ata_deg × 180 → 적기방향각",
                "aa_deg × 180 → 적기조준각",
                "distance_ft → 거리",
                "ego_altitude_ft → 내 고도",
                "ego_vc_kts → 내 속도",
                "closure_rate_kts → 접근속도",
                "energy_diff_ft → 에너지우위",
                "enm_in_wez → WEZ안 적기",
                "energy_advantage → 에너지우위(bool)",
                "side_flag → -1/0/1",
              ].map(s => (
                <div key={s} className="text-gray-500 truncate">{s}</div>
              ))}
            </div>
            <div className="text-xs text-gray-500 mt-1.5">
              행동: <code className="text-orange-400">set_action(alt 0-4, hdg 0-8, vel 0-4)</code>
            </div>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}
        </div>

        {/* 푸터 */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-sm text-gray-400 hover:text-white transition-colors"
          >
            취소
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors"
          >
            저장 후 팔레트에 추가
          </button>
        </div>
      </div>
    </div>
  )
}
