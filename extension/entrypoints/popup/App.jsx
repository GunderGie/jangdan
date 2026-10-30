import { useEffect, useRef, useState } from 'react'
import { browser } from 'wxt/browser'
import { MAX, analyzeText } from '../../../web/src/api.js'
import Notice from '../../../web/src/Notice.jsx'
import Result from '../../../web/src/Result.jsx'
import { pageMarks } from './marks.js'

// 아이콘을 누른 탭에서 선택한 글(프레임 안 포함)을 읽는다. 페이지에 표시할 때 쓰려고 탭과 프레임도 돌려준다.
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
    const pick = picks.find((r) => !r.result.stale) ?? picks[0]
    return pick ? { text: pick.result.text.trim(), tabId: tab.id, frameId: pick.frameId } : { text: '', tabId: tab.id }
  } catch {
    return { text: '' }
  }
}

function inPage(source, func, args = []) {
  return browser.scripting
    .executeScript({ target: { tabId: source.tabId, frameIds: [source.frameId] }, func, args })
    .then(([r]) => r.result)
}

// 표시는 프레임마다 남으므로 개수 세기와 지우기는 모든 프레임에서 한다. 실패하면 맨 위 프레임만 한다.
function inFrames(tabId, func, args = []) {
  const run = (target) =>
    browser.scripting.executeScript({ target: { tabId, ...target }, func, args }).then((rs) => rs.map((r) => r.result ?? {}))
  return run({ allFrames: true }).catch(() => run({ frameIds: [0] }))
}

export default function App() {
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [result, setResult] = useState(null)
  const [run, setRun] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [source, setSource] = useState(null) // 선택 글을 읽은 탭과 프레임
  const [marked, setMarked] = useState(false)
  const [hadMarks, setHadMarks] = useState(false) // 팝업을 열 때 페이지에 표시가 있었는지
  const [marking, setMarking] = useState(false)
  const [tabId, setTabId] = useState(null)
  const refreshed = useRef(false)
  const [markNote, setMarkNote] = useState('')
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
    selectedText().then((s) => {
      setText(s.text)
      setSource(s.text ? s : null)
      setTabId(s.tabId ?? null)
      setReady(true)
      if (s.text && Array.from(s.text).length <= MAX) analyze(s.text)
      // 페이지에 표시가 남아 있으면(표시를 켜 둔 상태) 분석이 끝나는 대로 지금 선택한 글로 표시를 새로 고친다.
      // 선택이 없거나 분석이 실패해도 지우기 버튼은 보인다.
      if (s.tabId)
        inFrames(s.tabId, pageMarks, ['count'])
          .then((rs) => setHadMarks(rs.some((r) => r.count > 0)))
          .catch(() => {})
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (result) resultRef.current?.focus({ preventScroll: true })
  }, [result])

  // 페이지 표시는 페이지에서 읽은 글을 그대로 분석한 결과에만 쓴다(고친 글은 페이지와 맞지 않는다).
  const canMark = source && result && result.text === source.text

  useEffect(() => {
    if (!canMark || !hadMarks || refreshed.current) return
    refreshed.current = true
    markPage()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canMark, hadMarks])

  async function markPage() {
    const REASONS = {
      nosel: '선택한 글을 찾지 못했습니다. 글을 다시 선택해 주세요.',
      input: '입력 칸 안의 글에는 표시할 수 없습니다.',
      editable: '편집 중인 글에는 표시하지 않습니다.',
      shadow: '이 영역의 글에는 표시할 수 없습니다.',
    }
    setMarking(true)
    try {
      // 다른 프레임에 남은 표시도 지운다. 실패해도 선택한 프레임의 표시는 apply가 지운다.
      const old = await inFrames(source.tabId, pageMarks, ['clear']).catch(() => [])
      const r = await inPage(source, pageMarks, ['apply', result.text, result.long_positions])
      r.cleared += old.reduce((n, x) => n + (x.cleared ?? 0), 0)
      setMarked(r.marked > 0)
      setHadMarks(false)
      const done = r.marked
        ? `${r.marked}곳에 표시했습니다.${r.missed ? ` ${r.missed}곳은 페이지에서 찾지 못했습니다.` : ''}`
        : r.missed
          ? '페이지에서 표시할 자리를 찾지 못했습니다.'
          : '표시할 장음이 없습니다.'
      setMarkNote(REASONS[r.reason] ?? (r.cleared ? `표시를 새로 고쳤습니다. ${done}` : done))
    } catch {
      setMarkNote('페이지에 표시하지 못했습니다. 페이지를 새로 고친 뒤 다시 선택해 주세요.')
    } finally {
      setMarking(false)
    }
  }

  async function clearPage() {
    try {
      await inFrames(tabId, pageMarks, ['clear'])
      setMarked(false)
      setHadMarks(false)
      setMarkNote('표시를 지웠습니다.')
    } catch {
      setMarkNote('표시를 지우지 못했습니다.')
    }
  }

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

      {(canMark || marked || hadMarks) && (
        <div className="page-marks">
          {canMark && !marked && (
            <button type="button" className="secondary" disabled={busy || marking} onClick={markPage}>
              페이지에 장음 표시
            </button>
          )}
          {(marked || hadMarks) && (
            <button type="button" className="link" disabled={marking} onClick={clearPage}>
              표시 지우기
            </button>
          )}
          {markNote && (
            <p className="hint" role="status">
              {markNote}
            </p>
          )}
        </div>
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
