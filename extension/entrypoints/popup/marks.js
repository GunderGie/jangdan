// 페이지 안의 장음 표시. scripting.executeScript로 탭에 넣어 실행하므로 이 함수 밖의 것을 쓰지 않는다.
// action: 'count'(표시 개수), 'apply'(있던 표시를 지우고 지금 선택한 글에 표시), 'clear'(지우기)
// apply의 text는 팝업이 분석한 선택 글, longs는 그 글에서 장음 음절의 위치(코드 포인트)다.
export function pageMarks(action, text = '', longs = []) {
  const marks = () => document.querySelectorAll('span.jangdan-long')
  if (action === 'count') return { count: marks().length }

  // 지우기: 감싸면 원래 노드에 앞쪽 글이, 새로 나뉜 노드에 뒤쪽 글이 남는다. 원래 노드에 되붙여 페이지가 쥔 노드를 살린다.
  // 선택이 지울 표시에 걸쳐 있으면 되붙인 노드의 같은 자리로 옮겨, 이어서 새 선택에 표시할 수 있게 한다.
  const sel = getSelection()
  const old = sel?.rangeCount ? sel.getRangeAt(0) : null
  const pts = old ? [[old.startContainer, old.startOffset], [old.endContainer, old.endOffset]] : []
  let cleared = 0
  for (const span of marks()) {
    cleared++
    const prev = span.previousSibling
    const next = span.nextSibling
    const inner = span.firstChild
    if (!(prev?.nodeType === 3 && next?.nodeType === 3 && inner?.nodeType === 3 && span.childNodes.length === 1)) {
      span.replaceWith(...span.childNodes)
      continue
    }
    const parent = span.parentNode
    const at = Array.prototype.indexOf.call(parent.childNodes, span)
    const base = prev.length
    const offsets = [base, base + inner.length, base + inner.length + next.length] // span 앞, span과 next 사이, next 뒤
    for (const pt of pts) {
      if (pt[0] === inner) pt.splice(0, 2, prev, base + pt[1])
      else if (pt[0] === next) pt.splice(0, 2, prev, base + inner.length + pt[1])
      else if (pt[0] === span) pt.splice(0, 2, prev, offsets[pt[1] ? 1 : 0])
      else if (pt[0] === parent && pt[1] >= at) {
        if (pt[1] <= at + 2) pt.splice(0, 2, prev, offsets[pt[1] - at])
        else pt[1] -= 2
      }
    }
    prev.appendData(inner.data + next.data)
    next.remove()
    span.remove()
  }
  if (cleared && old) sel.setBaseAndExtent(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
  if (action === 'clear') {
    document.getElementById('jangdan-style')?.remove()
    return { cleared }
  }

  const none = (reason) => ({ reason, cleared, marked: 0, missed: longs.length })
  if (!sel?.rangeCount) return none('nosel')
  const range = sel.getRangeAt(0)
  if (range.collapsed) return none('input') // 입력 칸 안의 선택은 문서 범위가 접혀 있다
  const root = range.commonAncestorContainer
  if (root.getRootNode() !== document) return none('shadow') // shadow DOM 안에는 문서의 스타일이 닿지 않는다
  const host = root.nodeType === 1 ? root : root.parentElement
  if (document.designMode === 'on' || host?.isContentEditable) return none('editable')

  // 선택 글(Selection.toString)에 들어가는 글자만 센다: 보이고, 선택할 수 있는 글자
  const seen = new Map()
  const shown = (el) => {
    if (!seen.has(el)) {
      const s = getComputedStyle(el)
      seen.set(el, el.getClientRects().length > 0 && s.visibility !== 'hidden' &&
        (s.userSelect || s.webkitUserSelect) !== 'none' && !el.closest('script,style,noscript,textarea,template'))
    }
    return seen.get(el)
  }
  const nodes = []
  if (root.nodeType === 3) nodes.push(root)
  else {
    // 선택 시작부터 끝까지만 훑는다(공통 조상 전체를 훑으면 긴 페이지에서 멈춘다)
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let n = range.startContainer
    if (n.nodeType !== 3) {
      walker.currentNode = n.childNodes[range.startOffset] ?? n
      n = walker.currentNode.nodeType === 3 ? walker.currentNode : walker.nextNode()
    } else walker.currentNode = n
    for (; n && range.comparePoint(n, 0) <= 0; n = walker.nextNode()) if (range.intersectsNode(n)) nodes.push(n)
  }
  const chars = [] // 공백이 아닌 글자: [노드, 시작, 길이, 글자, 감쌀 수 있는지]
  for (const node of nodes) {
    const el = node.parentElement
    if (!el || !shown(el)) continue
    const wrappable = el.namespaceURI === 'http://www.w3.org/1999/xhtml' && !el.isContentEditable // SVG 안에서는 span이 그려지지 않는다
    const end = node === range.endContainer ? range.endOffset : node.data.length
    for (let i = node === range.startContainer ? range.startOffset : 0; i < end; ) {
      const ch = String.fromCodePoint(node.data.codePointAt(i))
      if (!/\s/.test(ch)) chars.push([node, i, ch.length, ch, wrappable])
      i += ch.length
    }
  }

  // 선택 글과 페이지 글자를 공백을 빼고 차례로 맞댄다. 한 번 어긋나면 그 뒤는 믿지 않고 표시하지 않는다.
  const wanted = new Set(longs)
  const targets = []
  let k = 0
  let lost = false
  let missed = 0
  Array.from(text).forEach((ch, p) => {
    if (/\s/.test(ch)) return
    const c = lost ? null : chars[k++]
    if (!c || c[3] !== ch) lost = true
    if (!wanted.has(p)) return
    if (!lost && c[4]) targets.push(c)
    else missed++
  })

  if (!document.getElementById('jangdan-style')) {
    const style = document.createElement('style')
    style.id = 'jangdan-style'
    style.textContent =
      'span.jangdan-long{display:inline!important}' +
      'span.jangdan-long::after{content:"ː"!important;color:#d4412c!important;font-weight:700!important}'
    document.head.append(style)
  }
  // 같은 노드 안에서는 뒤에서부터 감싼다. 감싸도 원래 노드에 앞쪽 글이 남아 앞쪽 위치는 그대로다.
  let lastSpan = null
  targets.reverse().forEach(([node, i, len]) => {
    const r = document.createRange()
    r.setStart(node, i)
    r.setEnd(node, i + len)
    const span = document.createElement('span')
    span.className = 'jangdan-long'
    r.surroundContents(span)
    lastSpan ??= span // 처음 감싼 것이 문서에서 마지막 표시다
  })
  // 선택의 끝 글자를 감싸면 선택 끝이 span 앞으로 밀린다. 끝을 span 뒤로 되돌려, 다시 열 때도 같은 글을 읽게 한다.
  if (lastSpan) {
    const live = sel.getRangeAt(0)
    const after = live.comparePoint(lastSpan, 1) > 0
    sel.setBaseAndExtent(live.startContainer, live.startOffset,
      after ? lastSpan.nextSibling : live.endContainer, after ? 0 : live.endOffset)
  }
  return { cleared, marked: targets.length, missed }
}
