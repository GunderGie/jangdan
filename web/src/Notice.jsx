// 판별 방식 안내(접어 둠). 웹 화면과 확장 팝업이 함께 쓴다.
export default function Notice() {
  return (
    <details className="notice">
      <summary>판별 방식 안내</summary>
      <ul>
        <li>한국어기초사전을 먼저 따르고, 기초사전에 없는 단어는 표준국어대사전을 씁니다.</li>
        <li>두 사전의 발음이 다를 수 있습니다. 표준국어대사전 발음 우선 적용과 링크는 추후 제공합니다.</li>
        <li>뜻이 갈리는 단어는 LLM이 문맥으로 판별하므로 틀릴 수 있습니다.</li>
        <li>문맥 판별에 쓰는 LLM API 제공자의 정책에 따라 입력한 원문이 수집될 수 있습니다.</li>
      </ul>
    </details>
  )
}
