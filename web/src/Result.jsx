import { useCallback, useEffect, useRef, useState } from 'react'
import Evidence, { STATUS } from './Evidence.jsx'

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

// 분석 결과(집계, 원고, 복사, 근거 창). 웹 화면과 확장 팝업이 함께 쓴다.
// 새 결과마다 key를 바꿔 그리면 고른 단어와 복사 상태가 처음으로 돌아간다.
export default function Result({ ref, result, busy, useLlm, onRetry, onEdit, editLabel = '원고 고치기' }) {
  const [picked, setPicked] = useState(null)
  const [copied, setCopied] = useState(false)
  const [manualCopy, setManualCopy] = useState(false)
  const opener = useRef(null)

  const pick = useCallback((it, el) => {
    opener.current = el
    setPicked(it)
  }, [])
  const close = useCallback(() => {
    setPicked(null)
    // 근거를 닫으면 누른 단어로 돌아간다. dialog가 열려 있는 동안은 바깥에 포커스를 줄 수 없어 닫힌 뒤에 옮긴다.
    const el = opener.current
    requestAnimationFrame(() => (el && el.tabIndex >= 0 ? el : ref?.current)?.focus({ preventScroll: true }))
  }, [ref])

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(result.rendered)
      setCopied(true)
    } catch {
      setManualCopy(true) // http로 접속했거나 권한이 없으면 클립보드를 쓸 수 없다
    }
  }

  const count = (f) => result.items.filter(f).length
  const longWords = count((it) => it.status === 'long')
  const undecided = count((it) => it.status === 'undecided')
  const byLlm = count((it) => it.method === 'llm')
  // 호출 실패와 형식이 틀린 답만 센다. 「문맥으로 정하지 못함」은 모델이 정상으로 답한 것이다.
  const llmFailed = count((it) => it.status === 'undecided' && /LLM (호출 실패|응답에)/.test(it.reason))
  const llmLimited = useLlm && result.meta?.llm_limited && undecided > 0
  const llmMissing = useLlm && !result.meta?.llm && !result.meta?.llm_limited && undecided > 0

  return (
    <section className="result" ref={ref} tabIndex={-1} aria-label="장음 표시 결과">
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
          <button type="button" className="link" disabled={busy} onClick={onRetry}>
            {busy ? '다시 시도하는 중…' : '재시도'}
          </button>
        </p>
      )}
      <Script result={result} picked={picked} onPick={pick} />
      <p className="hint">
        단어를 누<span className="mark" aria-hidden="true">ː</span>르면 표시한 까닭이 나옵니다.
        {llmMissing && ' 서버에 LLM 키가 없어 문맥 판별은 하지 않았습니다.'}
        {llmLimited && ' 오늘 쓸 수 있는 문맥 판별 횟수를 다 써서 문맥 판별은 하지 않았습니다.'}
      </p>
      <div className="actions">
        <button type="button" className="primary" onClick={copy}>
          {copied ? '복사했습니다' : '장음 기호(ː) 넣어 복사'}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={onEdit}>
          {editLabel}
        </button>
      </div>
      {manualCopy && (
        <div className="manual">
          <label htmlFor="copy-text">자동으로 복사하지 못했습니다. 아래 글을 길게 눌러 복사해 주세요.</label>
          <textarea id="copy-text" readOnly value={result.rendered} onFocus={(e) => e.target.select()} autoFocus />
        </div>
      )}
      {picked && <Evidence item={picked} onClose={close} />}
    </section>
  )
}
