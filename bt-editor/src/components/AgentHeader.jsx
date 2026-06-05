import { useRef } from 'react'

export default function AgentHeader({ agentName, setAgentName, description, setDescription, onExport, onExportZip, onImport, onReset }) {
  const fileInputRef = useRef(null)

  function handleImportClick() {
    fileInputRef.current.click()
  }

  function handleFileChange(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (evt) => onImport(evt.target.result)
    reader.readAsText(file)
    e.target.value = ''
  }

  return (
    <header className="flex items-center gap-3 px-4 py-2 bg-gray-900 border-b border-gray-700 shrink-0">
      <div className="flex items-center gap-1 mr-2">
        <span className="text-lg">✈️</span>
        <span className="text-white font-bold text-sm tracking-wide">BT Editor</span>
      </div>

      <div className="flex items-center gap-1">
        <label className="text-gray-400 text-xs">이름</label>
        <input
          type="text"
          value={agentName}
          onChange={e => setAgentName(e.target.value)}
          placeholder="my_agent"
          className="bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400 w-32"
        />
      </div>

      <div className="flex items-center gap-1 flex-1">
        <label className="text-gray-400 text-xs shrink-0">설명</label>
        <input
          type="text"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="나의 전투기 전략 설명..."
          className="bg-gray-800 text-white text-sm px-2 py-1 rounded border border-gray-600 focus:outline-none focus:border-blue-400 w-full"
        />
      </div>

      <div className="flex items-center gap-2 ml-auto shrink-0">
        <button
          onClick={onReset}
          className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded transition-colors"
          title="튜토리얼 트리로 초기화"
        >
          🔄 초기화
        </button>
        <button
          onClick={handleImportClick}
          className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded transition-colors"
        >
          📥 불러오기
        </button>
        <button
          onClick={onExport}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-700 hover:bg-blue-600 text-white text-xs rounded transition-colors"
        >
          📤 YAML
        </button>
        <button
          onClick={onExportZip}
          className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-500 text-white text-xs rounded transition-colors font-semibold"
          title="제출용 ZIP 패키지 다운로드 (yaml + nodes/ 폴더 포함)"
        >
          📦 제출 ZIP
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".yaml,.yml"
          onChange={handleFileChange}
          className="hidden"
        />
      </div>
    </header>
  )
}
