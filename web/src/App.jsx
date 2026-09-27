import { useCallback, useEffect, useRef, useState } from 'react'
import Evidence, { STATUS } from './Evidence.jsx'

const MAX = 2000
const SAMPLE =
  '오늘 아침 서울 하늘에서 눈이 내렸습니다. 시민들은 말을 아끼며 출근길을 서둘렀습니다. ' +
  '방화 설비를 점검하던 직원은 사람이 많아 보인다고 전했습니다.'
const ERRORS = {
  411: '요청 크기를 알 수 없습니다. 다시 시도해 주세요.',
  413: '원고가 너무 깁니다.',
  422: `원고를 1자 이상 ${MAX.toLocaleString()}자 이하로 넣어 주세요.`,
  503: '사전 DB에 연결하지 못했습니다. 서버의 .env 설정을 확인해 주세요.',
}

// API의 위치는 코드 포인트 기준이다. 장음 음절만 따로 감싸고 나머지는 이어 쓴다.
function marked(chars, from, to, longs, order) {
  const out = []
  let run = from
  for (let i = from; i < to; i++) {
    if (!longs.has(i)) continue
    if (i > run) out.push(chars.slice(run, i).join(''))
    out.push(
      <span key={i} className="syl">
        {chars[i]}
        <span className="mark" style={{ '--i': order.n++ }}>
          ː
        </span>
      </span>,
    )
    run = i + 1
  }
  if (run < to) out.push(chars.slice(run, to).join(''))
  return out
}

function Script({ result, picked, onPick }) {
  const chars = Array.from(result.text)
  const longs = new Set(result.long_positions)
  const order = { n: 0 }
  const parts = []
  let pos = 0
  for (const it of [...result.items].sort((a, b) => a.start - b.start)) {
    if (it.start < pos) continue // 겹치는 항목은 앞 항목을 따른다
    if (it.start > pos) parts.push(<span key={`t${pos}`}>{marked(chars, pos, it.start, longs, order)}</span>)
    // 표시가 있는 단어만 키보드로 옮겨 다닌다(짧은 원고도 단어가 수백 개라서). 나머지도 누르면 근거가 나온다.
    const marked_ = it.status === 'long' || it.status === 'undecided' || it.method === 'llm'
    const cls = ['word', it.status, it.method === 'llm' ? 'by-llm' : '', picked === it ? 'picked' : '']
    parts.push(
      <span
        key={`w${it.start}`}
        role={marked_ ? 'button' : undefined}
        tabIndex={marked_ ? 0 : undefined}
        className={cls.join(' ')}
        aria-label={marked_ ? `${it.surface}, ${STATUS[it.status]}` : undefined}
        onClick={(e) => onPick(it, e.currentTarget)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onPick(it, e.currentTarget)
          }
        }}
      >
        {marked(chars, it.start, it.end, longs, order)}
      </span>,
    )
    pos = it.end
  }
  if (pos < chars.length) parts.push(<span key="tail">{marked(chars, pos, chars.length, longs, order)}</span>)
  return <div className="script sheet">{parts}</div>
}

export default function App() {
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState(null)
  const [copied, setCopied] = useState(false)
  const [manualCopy, setManualCopy] = useState(false)
  const opener = useRef(null)
  const resultRef = useRef(null)
  const inputRef = useRef(null)
  const length = Array.from(text).length
  const tooLong = length > MAX

  const pick = useCallback((it, el) => {
    opener.current = el
    setPicked(it)
  }, [])
  const close = useCallback(() => {
    setPicked(null)
    // 근거를 닫으면 누른 단어로 돌아간다. dialog가 열려 있는 동안은 바깥에 포커스를 줄 수 없어 닫힌 뒤에 옮긴다.
    const el = opener.current
    requestAnimationFrame(() => (el && el.tabIndex >= 0 ? el : resultRef.current)?.focus({ preventScroll: true }))
  }, [])

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

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
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, llm: useLlm }),
      })
      if (!res.ok) throw new Error(ERRORS[res.status] || `분석하지 못했습니다(응답 ${res.status}).`)
      const body = await res.json().catch(() => null)
      if (!body || typeof body.text !== 'string' || !Array.isArray(body.items)) throw new Error('서버 응답을 읽지 못했습니다.')
      setResult(body)
      setPicked(null)
      setManualCopy(false)
    } catch (e) {
      setError(e instanceof TypeError ? '서버에 연결하지 못했습니다. API 서버가 켜져 있는지 확인해 주세요.' : e.message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(result.rendered)
      setCopied(true)
      setError('')
    } catch {
      setManualCopy(true) // http로 접속했거나 권한이 없으면 클립보드를 쓸 수 없다
    }
  }

  function edit() {
    setResult(null)
    setPicked(null)
    setError('')
  }

  const count = (f) => (result ? result.items.filter(f).length : 0)
  const longWords = count((it) => it.status === 'long')
  const undecided = count((it) => it.status === 'undecided')
  const byLlm = count((it) => it.method === 'llm')
  // 호출 실패와 형식이 틀린 답만 센다. 「문맥으로 정하지 못함」은 모델이 정상으로 답한 것이다.
  const llmFailed = count((it) => it.status === 'undecided' && /LLM (호출 실패|응답에)/.test(it.reason))
  const llmMissing = result && useLlm && !result.meta?.llm && undecided > 0

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
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            <span>뜻이 갈리는 단어는 문맥으로 판별(LLM)</span>
          </label>
          <button type="button" className="primary" disabled={!text.trim() || tooLong || busy} onClick={analyze}>
            {busy ? '표시하는 중…' : '장음 표시하기'}
          </button>
        </section>
      ) : (
        <section className="result" ref={resultRef} tabIndex={-1} aria-label="장음 표시 결과">
          <div className="tally">
            <span>
              <b className="swatch long-swatch">ː</b>
              장음 {longWords}
            </span>
            {byLlm > 0 && (
              <span>
                <b className="swatch llm-swatch" />
                문맥 판별 {byLlm}
              </span>
            )}
            {undecided > 0 && (
              <span>
                <b className="swatch undecided-swatch" />
                판별 필요 {undecided}
              </span>
            )}
          </div>
          {llmFailed > 0 && (
            <p className="retry" role="status">
              문맥 판별 실패 {llmFailed}곳.{' '}
              <button type="button" className="link" disabled={busy} onClick={analyze}>
                {busy ? '다시 시도하는 중…' : '재시도'}
              </button>
            </p>
          )}
          <Script result={result} picked={picked} onPick={pick} />
          <p className="hint">
            단어를 누<span className="mark" aria-hidden="true">ː</span>르면 표시한 까닭이 나옵니다.
            {llmMissing && ' 서버에 LLM 키가 없어 문맥 판별은 하지 않았습니다.'}
          </p>
          <div className="actions">
            <button type="button" className="primary" onClick={copy}>
              {copied ? '복사했습니다' : '장음 기호(ː) 넣어 복사'}
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={edit}>
              원고 고치기
            </button>
          </div>
          {manualCopy && (
            <div className="manual">
              <label htmlFor="copy-text">자동으로 복사하지 못했습니다. 아래 글을 길게 눌러 복사해 주세요.</label>
              <textarea id="copy-text" readOnly value={result.rendered} onFocus={(e) => e.target.select()} autoFocus />
            </div>
          )}
        </section>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <details className="notice">
        <summary>판별 방식 안내</summary>
        <ul>
          <li>한국어기초사전을 먼저 따르고, 기초사전에 없는 단어는 표준국어대사전을 씁니다.</li>
          <li>두 사전의 발음이 다를 수 있습니다. 표준국어대사전 발음 우선 적용과 링크는 추후 제공합니다.</li>
          <li>뜻이 갈리는 단어는 LLM이 문맥으로 판별하므로 틀릴 수 있습니다.</li>
        </ul>
      </details>

      <footer className="colophon">발음과 뜻풀이: 국립국어원 한국어기초사전·표준국어대사전(CC BY-SA 2.0 KR)</footer>

      {picked && <Evidence item={picked} onClose={close} />}
    </main>
  )
}
