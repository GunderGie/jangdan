// 웹 화면과 브라우저 확장이 함께 쓰는 분석 API 호출
export const MAX = 2000
const ERRORS = {
  411: '요청 크기를 알 수 없습니다. 다시 시도해 주세요.',
  413: '원고가 너무 깁니다.',
  422: `원고를 1자 이상 ${MAX.toLocaleString()}자 이하로 넣어 주세요.`,
  429: '요청이 너무 많습니다. 1분 뒤에 다시 시도해 주세요.',
  503: '사전 DB에 연결하지 못했습니다. 서버의 .env 설정을 확인해 주세요.',
}

// base가 비어 있으면 화면과 같은 주소의 API를 부른다. 실패하면 화면에 띄울 문구로 Error를 던진다.
export async function analyzeText(text, llm, base = '') {
  let res
  try {
    res = await fetch(`${base}/api/analyze`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, llm }),
    })
  } catch {
    throw new Error('서버에 연결하지 못했습니다. API 서버가 켜져 있는지 확인해 주세요.')
  }
  if (!res.ok) throw new Error(ERRORS[res.status] || `분석하지 못했습니다(응답 ${res.status}).`)
  const body = await res.json().catch(() => null)
  if (!body || typeof body.text !== 'string' || !Array.isArray(body.items)) throw new Error('서버 응답을 읽지 못했습니다.')
  return body
}
