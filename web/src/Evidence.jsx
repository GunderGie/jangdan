import { useEffect, useRef } from 'react'

export const STATUS = { long: '장음', short: '단음', undecided: '판별 필요', unknown: '확인 불가' }
const METHOD = { dictionary: '사전 발음', rule: '표준발음법 규칙', llm: '문맥 판별(LLM)' }
const SOURCE = { krdict: '한국어기초사전', stdict: '표준국어대사전' }

// 표준국어대사전 일부 뜻풀이는 참조 대상 없이 「→ .」로만 남아 있다.
const definition = (d) => (!d || /^→\s*\.?$/.test(d.trim()) ? '뜻풀이 없음(사전에서 확인)' : d)

function Entry({ c, chosen }) {
  return (
    <div className={chosen ? 'entry chosen' : 'entry'}>
      <div className="entry-head">
        <span className="headword">
          {c.headword}
          <sup>{c.homonym_no || ''}</sup>
        </span>
        {c.origin && <span className="origin">{c.origin}</span>}
        {c.pron && <span className="pron">[{c.pron}]</span>}
        {c.long !== undefined && (
          <span className={`len ${c.long === null ? 'unknown' : c.long ? 'long' : 'short'}`}>
            {c.long === null ? '발음 없음' : c.long ? '장음' : '단음'}
          </span>
        )}
      </div>
      <p className="definition">
        <span className="pos">{c.pos}</span> {definition(c.definition)}
      </p>
      <a href={c.link} target="_blank" rel="noreferrer">
        {SOURCE[c.source]}에서 보기 ↗
      </a>
    </div>
  )
}

// 네이티브 dialog(showModal)라서 포커스가 안에 머물고 Esc로 닫힌다.
export default function Evidence({ item, onClose }) {
  const ref = useRef(null)
  const pressedOutside = useRef(false)
  useEffect(() => {
    const d = ref.current
    if (!d.open) typeof d.showModal === 'function' ? d.showModal() : d.setAttribute('open', '') // 구형 브라우저는 모달 없이 연다
    return () => d.open && d.close()
  }, [])

  const reason = item.reason.replace(/^LLM 판별\([^)]*\): /, '')
  const same = (c) => item.chosen && c.source === item.chosen.source && c.source_id === item.chosen.source_id
  const others = item.candidates.filter((c) => !same(c))
  return (
    <dialog
      ref={ref}
      className="evidence"
      aria-labelledby="evidence-word"
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      // 바깥(배경)을 눌렀다 떼면 닫는다. 안에서 글자를 끌어 선택하다 바깥에서 뗀 경우는 닫지 않는다.
      onPointerDown={(e) => (pressedOutside.current = e.target === ref.current)}
      onClick={(e) => pressedOutside.current && e.target === ref.current && onClose()}
    >
      <div className="evidence-body">
        <header>
          <h2 id="evidence-word">{item.surface}</h2>
          <span className={`verdict ${item.status}`}>{STATUS[item.status]}</span>
          <button type="button" className="close" onClick={onClose} aria-label="닫기" autoFocus>
            ×
          </button>
        </header>
        <dl>
          <dt>판단</dt>
          <dd>{METHOD[item.method] || '판단 보류'}</dd>
          <dt>까닭</dt>
          <dd>{reason}</dd>
          <dt>원형</dt>
          <dd>
            {item.lemma}
            {item.regularity && <span className="minor"> · {item.regularity} 활용</span>}
          </dd>
          {item.conj_pron && (
            <>
              <dt>활용 발음</dt>
              <dd>
                <span className="pron">[{item.conj_pron}]</span>
                <span className="minor"> 표준국어대사전</span>
                {item.note && <p className="note">{item.note}</p>}
              </dd>
            </>
          )}
        </dl>
        {item.chosen && (
          <>
            <h3>고른 동형어</h3>
            <Entry c={item.chosen} chosen />
          </>
        )}
        {others.length > 0 && (
          <>
            <h3>{item.chosen ? '다른 후보' : '후보'}</h3>
            {others.map((c) => (
              <Entry key={`${c.source}${c.source_id}`} c={c} />
            ))}
          </>
        )}
      </div>
    </dialog>
  )
}
