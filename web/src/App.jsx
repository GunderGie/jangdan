import { useEffect, useRef, useState } from 'react'
import { MAX, analyzeText } from './api.js'
import Notice from './Notice.jsx'
import Result from './Result.jsx'

const SAMPLE =
  '오늘 아침 서울 하늘에서 눈이 내렸습니다. 시민들은 말을 아끼며 출근길을 서둘렀습니다. ' +
  '방화 설비를 점검하던 직원은 사람이 많아 보인다고 전했습니다.'

export default function App() {
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [result, setResult] = useState(null)
  const [run, setRun] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const resultRef = useRef(null)
  const inputRef = useRef(null)
  const length = Array.from(text).length
  const tooLong = length > MAX

  // 결과가 바뀔 때만 포커스를 옮긴다. 처음 열 때(result가 계속 null)는 휴대폰 자판을 띄우지 않는다.
  const lastResult = useRef(null)
  useEffect(() => {
    if (lastResult.current !== result) (result ? resultRef : inputRef).current?.focus({ preventScroll: !!result })
    lastResult.current = result
  }, [result])

  async function analyze() {
    setBusy(true)
    setError('')
    try {
      setResult(await analyzeText(text, useLlm))
      setRun((n) => n + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function edit() {
    setResult(null)
    setError('')
  }

  return (
    <main className="page">
      <header className="masthead">
        <h1>
          <span className="logo-tri" aria-hidden="true">▶</span>장단<span className="logo-tri" aria-hidden="true">◀</span>
        </h1>
        <p>원고에서 길<span className="mark" aria-hidden="true">ː</span>게 읽을 음절을 표시하고, 표시한 까닭을 보여 줍니다.</p>
      </header>

      {!result ? (
        <section className="compose">
          <label htmlFor="script" className="eyebrow">
            원고
          </label>
          <textarea
            id="script"
            ref={inputRef}
            className="sheet"
            value={text}
            placeholder="읽을 원고를 붙여 넣으세요."
            aria-describedby="counter"
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <span id="counter" className={tooLong ? 'counter over' : 'counter'}>
              {length.toLocaleString()} / {MAX.toLocaleString()}자{tooLong && ' · 줄여 주세요'}
            </span>
            {!text && (
              <button type="button" className="link" onClick={() => setText(SAMPLE)}>
                예시 원고 넣기
              </button>
            )}
          </div>
          <label className="toggle">
            <input type="checkbox" checked={useLlm} disabled={busy} onChange={(e) => setUseLlm(e.target.checked)} />
            <span>뜻이 갈리는 단어는 문맥으로 판별(LLM)</span>
          </label>
          <button type="button" className="primary" disabled={!text.trim() || tooLong || busy} onClick={analyze}>
            {busy ? '표시하는 중…' : '장음 표시하기'}
          </button>
        </section>
      ) : (
        <Result key={run} ref={resultRef} result={result} busy={busy} useLlm={useLlm} onRetry={analyze} onEdit={edit} />
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <Notice />

      <footer className="colophon">발음과 뜻풀이: 국립국어원 한국어기초사전·표준국어대사전(CC BY-SA 2.0 KR)</footer>
    </main>
  )
}
