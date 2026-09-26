"""판별 필요(동형어의 장단이 섞인) 단어를 LLM으로 판별한다(기획안 5절 6단계).

판별 필요 단어가 있는 문장을 앞뒤 문장과 함께 한 요청에 모아 보내고, 문장마다 문맥에 맞는 동형어 번호를 JSON으로 받는다.
후보의 발음은 보여 주지 않는다. 답은 문장 단위(앞뒤 문장 포함)로 로컬 캐시(.cache/llm)에 둔다.
"""
import contextlib
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from prep.dicts import ROOT
from .llm import LLMError

CACHE_DIR = ROOT / ".cache" / "llm"
MAX_WORDS = 30   # 한 요청에 넣는 단어 수 상한. 문장은 나누지 않는다.
MAX_SENSES = 3   # 후보마다 보여 줄 뜻풀이 수
MAX_CONTEXT = 150  # 앞뒤 문장을 보여 줄 최대 글자 수

SYSTEM = """[문장 번호] 다음 문장에서 <w번호>…</w번호>로 표시한 단어가 어느 동형어로 쓰였는지 고른다.
- 표시한 문장과 후보의 품사·원어·뜻풀이를 보고 판단한다. 표시한 문장만으로 정할 수 없으면 그 아래의 앞 문장, 뒤 문장을 근거로 판단한다.
- 표시한 단어마다 답을 하나씩 낸다. sentence는 문장 번호, word는 단어 번호, text는 표시한 단어를 태그 없이 그대로 옮긴 것이다.
- 앞뒤 문장까지 보아도 정할 수 없거나 맞는 후보가 없으면 choice를 null로 한다.
- reason에는 고른 근거를 한국어 한 문장(30자 이내)으로 쓰고, 후보 번호는 쓰지 않는다."""

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"sentence": {"type": "integer"}, "word": {"type": "integer"}, "text": {"type": "string"},
                       "choice": {"type": ["integer", "null"]},
                       "reason": {"type": "string", "description": "고른 뜻을 설명하는 한국어 한 문장. 후보 번호는 쓰지 않는다."}},
        "required": ["sentence", "word", "text", "choice", "reason"]}}},
    "required": ["answers"],
}


def _senses(c, pos_names):
    picked = [d for p, d in c.senses if p in pos_names] or [d for _, d in c.senses]
    return " / ".join(picked[:MAX_SENSES])


def _ws(text):
    return " ".join(text.split())


def _plain(text):
    """줄바꿈을 없애고, 원고의 <, >는 단어 표시 태그와 헷갈리지 않게 전각으로 바꾼다."""
    return _ws(text).replace("<", "＜").replace(">", "＞")


def sentence_block(analysis, n, items):
    """문장 하나의 프롬프트 조각: 단어를 표시한 문장, 앞뒤 문장, 단어별 후보. 캐시 키이기도 하다."""
    text = analysis.text
    s, e = analysis.sentences[n]
    out, pos = [], s
    for k, it in enumerate(items, 1):
        out += [text[pos:it.start].replace("<", "＜").replace(">", "＞"), f"<w{k}>{text[it.start:it.end]}</w{k}>"]
        pos = it.end
    out.append(text[pos:e].replace("<", "＜").replace(">", "＞"))
    lines = [_ws("".join(out))]  # 원고 조각은 위에서 바꿨으므로 공백만 정리한다
    if n > 0:
        a, b = analysis.sentences[n - 1]
        lines.append(f"앞 문장: {_plain(text[a:b])[-MAX_CONTEXT:]}")
    if n + 1 < len(analysis.sentences):
        a, b = analysis.sentences[n + 1]
        lines.append(f"뒤 문장: {_plain(text[a:b])[:MAX_CONTEXT]}")
    for k, it in enumerate(items, 1):
        lines.append(f"단어 {k}: {_ws(it.surface)} (원형 {it.lemma})")  # 어절 중간 줄바꿈(PDF 복사 등)도 한 줄로
        for j, (c, _) in enumerate(it.candidates, 1):
            origin = f" {c.origin}" if c.origin else ""
            lines.append(f"  {j}) [{c.pos}]{origin} {_senses(c, it.pos_names)}")
    return "\n".join(lines)


def _valid(choice, it):
    return choice is None or (type(choice) is int and 1 <= choice <= len(it.candidates))


def _parse(raw, groups):
    """{문장 번호: {단어 번호: (후보 번호 또는 None, 근거)}}. 형식에 맞지 않거나 표시한 단어와 다른 답은 버린다."""
    try:
        answers = json.loads(raw)["answers"]
    except (ValueError, KeyError, TypeError) as e:
        raise LLMError("응답 형식 오류") from e
    out = {}
    for a in answers if isinstance(answers, list) else []:
        if not isinstance(a, dict) or "choice" not in a:
            continue
        i, k = a.get("sentence"), a.get("word")
        if type(i) is not int or not 1 <= i <= len(groups):
            continue
        items = groups[i - 1]
        if type(k) is not int or not 1 <= k <= len(items) or k in out.get(i, {}):
            continue
        if _ws(str(a.get("text", ""))) != _ws(items[k - 1].surface) or not _valid(a["choice"], items[k - 1]):
            continue
        reason = str(a.get("reason") or "").encode("utf-8", "replace").decode("utf-8").strip()  # 짝 없는 서로게이트 제거
        out.setdefault(i, {})[k] = (a["choice"], reason)
    return out


class Judge:
    """캐시는 문장 단위다. 같은 문장이라도 앞뒤 문장이 다르면 다시 판별한다."""

    def __init__(self, backend, cache_dir=CACHE_DIR):
        self.backend, self.cache_dir = backend, Path(cache_dir)
        self.calls = 0  # 실제로 호출한 횟수(캐시 제외)
        # 호출과 캐시 읽기·쓰기를 한 번에 하나씩 한다. 같은 문장을 두 번 보내지 않고, Windows의 파일 교체 충돌도 막는다.
        self._lock = threading.Lock()

    def resolve(self, analysis):
        """판별 필요 단어의 동형어를 골라 analysis를 고친다."""
        return self.resolve_many([analysis])[0]

    def resolve_many(self, analyses):
        """원고 여러 개의 판별 필요 단어를 한 요청으로 모아 보낸다. 문맥은 원고 안에서만 본다."""
        analyses = list(analyses)
        with self._lock:
            pending = {}  # 캐시 경로 → (조각, [단어 목록, ...]). 되풀이된 문장(앞뒤 문장까지 같음)은 한 번만 보낸다.
            for analysis in analyses:
                groups = {}
                for it in analysis.undecided:
                    groups.setdefault(it.sentence, []).append(it)
                for n in sorted(groups):
                    items = groups[n]
                    block = sentence_block(analysis, n, items)
                    path = self.cache_dir / f"{self._key(block)}.json"
                    answers = self._read(path, items)
                    if answers is not None:
                        self._apply(items, answers)
                    else:
                        pending.setdefault(path, (block, []))[1].append(items)
            packs, size = [[]], 0
            for path, (block, same) in pending.items():
                if packs[-1] and size + len(same[0]) > MAX_WORDS:
                    packs.append([])
                    size = 0
                packs[-1].append((path, block, same))
                size += len(same[0])
            # 한도 초과·연결 실패 등(LLMError.stop)이거나 연달아 두 번 실패하면(설정 오류 등) 남은 요청은 보내지 않는다
            stopped, in_row = None, 0
            for pack in packs:
                error = stopped
                if pack and error is None:
                    try:
                        self._call(pack)
                        in_row = 0
                        continue
                    except LLMError as e:
                        error, in_row = e, in_row + 1
                        stopped = e if e.stop or in_row >= 2 else None
                for _, _, same in pack:
                    for items in same:
                        for it in items:
                            it.reason = f"판별 필요: LLM 호출 실패({error})"
        return analyses

    def _key(self, block):
        key = json.dumps([self.backend.id, SYSTEM, SCHEMA, block], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()

    def _call(self, pack):
        """pack: [(캐시 경로, 조각, [단어 목록, ...]), ...]. 호출이 실패하면 LLMError를 낸다."""
        prompt = "\n\n".join(f"[문장 {i}] {block}" for i, (_, block, _) in enumerate(pack, 1))
        self.calls += 1
        got = _parse(self.backend(SYSTEM, prompt, SCHEMA), [same[0] for _, _, same in pack])
        for i, (path, block, same) in enumerate(pack, 1):
            answers = got.get(i, {})
            if len(answers) == len(same[0]):  # 모든 단어에 올바른 답이 있는 문장만 캐시한다
                self._write(path, block, answers)
            for items in same:
                self._apply(items, answers)

    def _apply(self, items, answers):
        for k, it in enumerate(items, 1):
            if k not in answers:
                it.reason = "판별 필요: LLM 응답에 이 단어의 올바른 답이 없음"
            elif answers[k][0] is None:
                it.reason = f"판별 필요: LLM이 문맥으로 정하지 못함({answers[k][1]})"
            else:
                it.choose(answers[k][0] - 1, "llm", f"LLM 판별({self.backend.model}): {answers[k][1]}")

    @staticmethod
    def _read(path, items):
        """캐시된 답. 없거나 읽을 수 없거나 모자라면 None(다시 호출한다)."""
        try:
            saved = json.loads(path.read_text("utf-8"))["answers"]
            answers = {int(k): (v[0], str(v[1])) for k, v in saved.items()}
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None
        if set(answers) != set(range(1, len(items) + 1)) \
                or not all(_valid(answers[k][0], it) for k, it in enumerate(items, 1)):
            return None
        return answers

    def _write(self, path, block, answers):
        """캐시는 쓸 수 있을 때만 쓴다. 실패해도 이번 판별 결과는 그대로 쓴다."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        except OSError:
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:  # ensure_ascii 기본값: 원고의 짝 없는 서로게이트도 쓸 수 있다
                json.dump({"backend": self.backend.id, "block": block, "answers": answers}, f)
            os.replace(tmp, path)
        except (OSError, ValueError):
            with contextlib.suppress(OSError):
                os.remove(tmp)


if __name__ == "__main__":
    import sys

    from .analyze import Analyzer
    from .llm import from_env

    backend = from_env()
    if backend is None:
        sys.exit("GEMINI_API_KEY 없음: .env에 넣는다")
    judge = Judge(backend)
    r = judge.resolve(Analyzer().analyze(" ".join(sys.argv[1:])))
    print(r.render())
    for it in r.items:
        if it.method == "llm" or it.status == "undecided":
            c = it.chosen
            print(f"  {it.surface}({it.lemma}) {it.status}: {it.reason}"
                  + (f" → {c.headword}{c.homonym_no} {c.origin} {c.definition(it.pos_names)}" if c else ""))
    print(f"호출 {judge.calls}회")
