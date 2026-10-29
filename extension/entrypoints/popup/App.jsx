import { useEffect, useRef, useState } from 'react'
import { browser } from 'wxt/browser'
import { MAX, analyzeText } from '../../../web/src/api.js'
import Result from '../../../web/src/Result.jsx'

// 아이콘을 누른 탭에서 선택한 글(프레임 안 포함)을 읽는다.
// 스크립트를 넣을 수 없는 페이지(chrome://, 웹 스토어)나 캔버스로 그리는 편집기에서는 빈 글이 된다.
async function selectedText() {
  try {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true })
    // 프레임마다 선택이 따로 남는다. 포커스가 다른 프레임으로 옮겨 간 프레임의 선택은 예전 것이라 뒤로 미룬다.
    const read = (allFrames) =>
      browser.scripting.executeScript({
        target: { tabId: tab.id, allFrames },
        func: () => {
          let stale = document.activeElement?.tagName === 'IFRAME'
          try {
            if (window.frameElement && parent.document.activeElement !== window.frameElement) stale = true
          } catch {
            // 출처가 다른 상위 문서는 읽을 수 없다
          }
          return { text: getSelection()?.toString() ?? '', stale }
        },
      })
    // 권한이 없는 프레임이 섞이면 전체가 실패할 수 있어 맨 위 프레임만 다시 읽는다.
    const results = await read(true).catch(() => read(false))
    const picks = results.filter((r) => r.result?.text.trim()).sort((a, b) => (a.frameId === 0 ? -1 : b.frameId === 0 ? 1 : 0))
    return (picks.find((r) => !r.result.stale) ?? picks[0])?.result.text.trim() ?? ''
  } catch {
    return ''
  }
}

export default function App() {
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [result, setResult] = useState(null)
  const [run, setRun] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const resultRef = useRef(null)
  const inputRef = useRef(null)
  const started = useRef(false)
  const length = Array.from(text).length
  const tooLong = length > MAX

  async function analyze(t = text) {
    setBusy(true)
    setError('')
    try {
      setResult(await analyzeText(t, useLlm, __API_BASE__))
      setRun((n) => n + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // 선택한 글이 있으면 바로 분석한다. 너무 길면 잘라 보내지 않고 줄여 달라고 한다.
  useEffect(() => {
    if (started.current) return
    started.current = true
    selectedText().then((t) => {
      setText(t)
      setReady(true)
      if (t && Array.from(t).length <= MAX) analyze(t)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (result) resultRef.current?.focus({ preventScroll: true })
  }, [result])

  function edit() {
    setResult(null)
    setError('')
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  return (
    <main className="page popup">
      <header className="masthead">
        <h1>
          <span className="logo-tri" aria-hidden="true">▶</span>장단<span className="logo-tri" aria-hidden="true">◀</span>
        </h1>
        <p>선택한 글에서 길<span className="mark" aria-hidden="true">ː</span>게 읽을 음절을 표시합니다.</p>
      </header>

      {!ready ? (
        <p className="hint">선택한 글을 읽는 중…</p>
      ) : !result ? (
        <section className="compose">
          <textarea
            ref={inputRef}
            className="sheet"
            value={text}
            placeholder="페이지에서 글을 선택한 뒤 아이콘을 누르거나, 여기에 붙여 넣으세요."
            aria-label="원고"
            aria-describedby="counter"
            autoFocus={!text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <span id="counter" className={tooLong ? 'counter over' : 'counter'}>
              {length.toLocaleString()} / {MAX.toLocaleString()}자{tooLong && ' · 줄여 주세요'}
            </span>
          </div>
          <label className="toggle">
            <input type="checkbox" checked={useLlm} disabled={busy} onChange={(e) => setUseLlm(e.target.checked)} />
            <span>뜻이 갈리는 단어는 문맥으로 판별(LLM)</span>
          </label>
          <button type="button" className="primary" disabled={!text.trim() || tooLong || busy} onClick={() => analyze()}>
            {busy ? '표시하는 중…' : '장음 표시하기'}
          </button>
        </section>
      ) : (
        <Result
          key={run}
          ref={resultRef}
          result={result}
          busy={busy}
          useLlm={useLlm}
          onRetry={() => analyze()}
          onEdit={edit}
          editLabel="글 고치기"
        />
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <footer className="colophon">발음과 뜻풀이: 국립국어원 한국어기초사전·표준국어대사전(CC BY-SA 2.0 KR)</footer>
    </main>
  )
}
