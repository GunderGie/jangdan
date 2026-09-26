import json
import os
import re

import httpx
import pytest

from core.judge import Judge, sentence_block
from core.llm import Gemini, LLMError
from prep.build import DB_PATH


@pytest.fixture(scope="module")
def analyzer():
    if not DB_PATH.exists():
        pytest.skip("data/jangdan.sqlite 없음: python -m prep.build")
    from core.analyze import Analyzer
    return Analyzer()


class Fake:
    """정해 둔 답을 돌려주는 공급자. answer(prompt)가 답 목록, JSON 문자열, 예외 중 하나를 낸다."""

    def __init__(self, answer, model="fake"):
        self.answer, self.model, self.id, self.prompts = answer, model, model, []

    def __call__(self, system, prompt, schema):
        self.prompts.append(prompt)
        out = self.answer(prompt)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps({"answers": out})


def ans(i, k, text, choice, reason=""):
    return {"sentence": i, "word": k, "text": text, "choice": choice, "reason": reason}


def pick(analysis, want_long):
    """판별 필요 단어마다 장음(또는 단음) 후보를 고르는 답. 캐시가 비어 있을 때 요청에 실리는 순서를 따른다."""
    groups = {}
    for it in analysis.undecided:
        groups.setdefault(it.sentence, []).append(it)
    out = [ans(i, k, it.surface, next(j for j, (_, v) in enumerate(it.candidates, 1) if v == want_long), "테스트")
           for i, n in enumerate(sorted(groups), 1) for k, it in enumerate(groups[n], 1)]
    return lambda prompt: out


def test_choose_long(analyzer, tmp_path):
    r = analyzer.analyze("하늘에서 눈이 내린다.")
    fake = Fake(pick(r, True))
    Judge(fake, tmp_path).resolve(r)
    assert r.render() == "하늘에서 눈ː이 내린다."
    it = r.items[1]
    assert (it.status, it.method, it.reason) == ("long", "llm", "LLM 판별(fake): 테스트")
    assert (it.chosen.homonym_no, it.to_dict()["chosen"]["homonym_no"]) == (4, 4)
    assert fake.prompts[0].startswith("[문장 1] 하늘에서 <w1>눈</w1>이 내린다.\n단어 1: 눈 (원형 눈)")
    assert "ː" not in fake.prompts[0]  # 발음은 보여 주지 않는다


def test_choose_verb_and_short(analyzer, tmp_path):
    r = analyzer.analyze("길을 묻는 사람")
    Judge(Fake(pick(r, True)), tmp_path).resolve(r)
    assert r.render() == "길을 묻ː는 사ː람"
    r = analyzer.analyze("눈을 감았다.")
    Judge(Fake(pick(r, False)), tmp_path).resolve(r)
    assert (r.items[0].status, r.items[0].method, r.long_positions) == ("short", "llm", [])


def test_choose_updates_conj_pron(analyzer):
    text = "칼을 숫돌에 가니 날이 섰다."
    it = analyzer.analyze(text).undecided[0]
    assert (it.lemma, it.conj_pron) == ("갈다", "가ː니")
    long_k = next(k for k, (_, v) in enumerate(it.candidates) if v)
    it.choose(long_k, "llm", "")
    assert (it.status, it.conj_pron, it.note) == ("long", "가ː니", None)
    it = analyzer.analyze(text).undecided[0]
    it.choose(next(k for k, (_, v) in enumerate(it.candidates) if v is False), "llm", "")
    assert (it.status, it.conj_pron, it.note) == ("short", None, None)  # 활용 발음은 다른(장음) 동형어의 것
    it = analyzer.analyze(text).undecided[0]
    it.candidates[0] = (it.candidates[0][0], None)
    it.choose(0, "llm", "근거")
    assert (it.status, it.reason, it.long_positions, it.conj_pron) == \
        ("unknown", "근거 / 고른 동형어에 발음 정보 없음", [], None)


def test_one_call_per_text(analyzer, tmp_path, monkeypatch):
    text = "눈이 오면 눈을 감는다. 날씨가 좋다. 사과를 먹었다."
    r = analyzer.analyze(text)
    fake = Fake(pick(r, False))
    Judge(fake, tmp_path).resolve(r)
    assert len(fake.prompts) == 1 and not r.undecided
    assert [x for x in fake.prompts[0].splitlines() if x.startswith("[문장")] == [
        "[문장 1] <w1>눈</w1>이 오면 <w2>눈</w2>을 감는다.", "[문장 2] <w1>사과</w1>를 먹었다."]
    monkeypatch.setattr("core.judge.MAX_WORDS", 1)  # 상한을 넘으면 문장 단위로 나눠 보낸다
    r = analyzer.analyze(text)
    fake = Fake(lambda p: [ans(1, 1, "눈", 1), ans(1, 2, "눈", 1), ans(1, 1, "사과", 1)])
    Judge(fake, tmp_path / "split").resolve(r)
    assert len(fake.prompts) == 2 and not r.undecided


def test_context_lines(analyzer, tmp_path):
    fake = Fake(lambda p: [ans(1, 1, "말", 3)])
    judge = Judge(fake, tmp_path)
    judge.resolve(analyzer.analyze("경마장에 갔다. 말이 빨랐다."))
    judge.resolve(analyzer.analyze("발표를 서둘렀다. 말이 빨랐다."))  # 같은 문장이라도 앞 문장이 다르면 다시 보낸다
    assert judge.calls == 2
    assert fake.prompts[0].startswith("[문장 1] <w1>말</w1>이 빨랐다.\n앞 문장: 경마장에 갔다.\n단어 1:")
    assert "앞 문장: 발표를 서둘렀다." in fake.prompts[1] and "뒤 문장" not in fake.prompts[1]


def test_context_limit_and_escape(analyzer):
    prev, nxt = "오늘은 " * 40 + "a<b 날씨가 좋다.", "c>d " + "내일은 " * 40 + "춥다고 한다."
    r = analyzer.analyze(f"{prev} 3<5>2라서 눈이 온다. {nxt}")
    assert len(r.sentences) == 3
    items = [it for it in r.undecided if it.lemma == "눈"]
    lines = sentence_block(r, 1, items).splitlines()
    wide = str.maketrans("<>", "＜＞")
    assert lines[:3] == ["3＜5＞2라서 <w1>눈</w1>이 온다.", "앞 문장: " + prev.translate(wide)[-150:],
                         "뒤 문장: " + nxt.translate(wide)[:150]]
    assert "a＜b" in lines[1] and "c＞d" in lines[2] and len(lines[1]) == len("앞 문장: ") + 150


def test_many_texts_in_one_request(analyzer, tmp_path):
    a, b, c = analyzer.analyze("눈이 온다."), analyzer.analyze("사과를 먹었다."), analyzer.analyze("눈이 온다.")
    fake = Fake(lambda p: [ans(1, 1, "눈", 4), ans(2, 1, "사과", 1)])
    assert Judge(fake, tmp_path).resolve_many([a, b, c]) == [a, b, c]
    assert len(fake.prompts) == 1 and "앞 문장" not in fake.prompts[0]  # 원고끼리는 문맥으로 섞지 않는다
    assert "[문장 3]" not in fake.prompts[0]  # 원고가 달라도 같은 조각은 한 번만 보낸다
    assert (a.render(), b.render(), c.render()) == ("눈ː이 온다.", "사과를 먹었다.", "눈ː이 온다.")


def word_answer(fail_at, error):
    """요청마다 표시한 단어에 후보 1을 답하고, fail_at에 든 번째 요청에서는 error를 낸다."""
    calls = []

    def answer(prompt):
        calls.append(prompt)
        if len(calls) in fail_at:
            return error
        return [ans(1, 1, re.search(r"<w1>(.+?)</w1>", prompt).group(1), 1)]
    return answer


@pytest.mark.parametrize("fail_at, error, statuses, sent, reason", [
    # 요청 내용 탓 실패는 그 묶음만 남기고 다음 요청을 보낸다
    ({2}, LLMError("API 오류 400"), ["short", "undecided", "short"], 3, "API 오류 400"),
    ({2}, "not json", ["short", "undecided", "short"], 3, "응답 형식 오류"),
    # 한도 초과·연결 실패, 또는 연달아 두 번 실패하면(설정 오류 등) 남은 요청을 보내지 않는다
    ({2}, LLMError("API 오류 429", stop=True), ["short", "undecided", "undecided"], 2, "API 오류 429"),
    ({1, 2, 3}, LLMError("API 오류 400"), ["undecided", "undecided", "undecided"], 2, "API 오류 400"),
])
def test_failure_across_packs(analyzer, tmp_path, monkeypatch, fail_at, error, statuses, sent, reason):
    monkeypatch.setattr("core.judge.MAX_WORDS", 1)
    rs = [analyzer.analyze(t) for t in ("눈이 온다.", "사과를 먹었다.", "방화 혐의로 체포됐다.")]
    fake = Fake(word_answer(fail_at, error))
    Judge(fake, tmp_path).resolve_many(rs)
    assert [r.items[0].status for r in rs] == statuses and len(fake.prompts) == sent
    assert rs[1].items[0].reason == f"판별 필요: LLM 호출 실패({reason})"


def test_surface_with_line_break(analyzer, tmp_path):
    r = analyzer.analyze("길을 묻\n는 사람")  # PDF에서 복사해 어절 중간에 줄이 바뀐 원고
    fake = Fake(lambda p: [ans(1, 1, "묻 는", 3)])
    Judge(fake, tmp_path).resolve(r)
    assert "<w1>묻 는</w1>" in fake.prompts[0] and "단어 1: 묻 는 (원형 묻다)" in fake.prompts[0]
    assert [it.method for it in r.items if it.lemma == "묻다"] == ["llm"]


def test_repeated_sentence_sent_once(analyzer, tmp_path):
    r = analyzer.analyze("날씨가 좋다. 눈이 온다. 춥다. 날씨가 좋다. 눈이 온다. 춥다.")
    fake = Fake(pick(r, True))
    Judge(fake, tmp_path).resolve(r)  # 앞뒤 문장까지 같은 문장은 한 번만 보낸다
    assert len(fake.prompts) == 1 and "[문장 2]" not in fake.prompts[0] and not r.undecided


def test_stop_after_failure(analyzer, tmp_path, monkeypatch):
    monkeypatch.setattr("core.judge.MAX_WORDS", 1)
    fake = Fake(lambda p: LLMError("ReadTimeout", stop=True))
    r = Judge(fake, tmp_path).resolve(analyzer.analyze("눈이 온다. 사과를 먹었다. 방화 혐의로 체포됐다."))
    assert len(fake.prompts) == 1  # 첫 요청이 실패하면 남은 요청은 보내지 않는다
    assert {it.reason for it in r.undecided} == {"판별 필요: LLM 호출 실패(ReadTimeout)"} and len(r.undecided) == 3


def test_no_call_without_undecided(analyzer, tmp_path):
    fake = Fake(lambda p: [])
    Judge(fake, tmp_path).resolve(analyzer.analyze("그 사실을 압니다."))
    assert fake.prompts == []


def test_cache_by_sentence(analyzer, tmp_path):
    text = "진심으로 사과했다."
    first = Judge(Fake(pick(analyzer.analyze(text), True)), tmp_path)
    assert first.resolve(analyzer.analyze(text)).render() == "진심으로 사ː과했다." and first.calls == 1
    again = Judge(Fake(lambda p: LLMError("호출되면 안 됨")), tmp_path)
    assert again.resolve(analyzer.analyze(text)).render() == "진심으로 사ː과했다." and again.calls == 0
    # 캐시에 있는 문장(앞뒤 문장까지 같음)은 빼고 새 문장만 보낸다
    Judge(Fake(pick(analyzer.analyze("진심으로 사과했다. 날씨가 좋다."), True)), tmp_path).resolve(
        analyzer.analyze("진심으로 사과했다. 날씨가 좋다."))
    fake = Fake(lambda p: [ans(1, 1, "눈", 4)])
    r = Judge(fake, tmp_path).resolve(analyzer.analyze("진심으로 사과했다. 날씨가 좋다. 눈이 온다."))
    assert r.render() == "진심으로 사ː과했다. 날씨가 좋ː다. 눈ː이 온다."
    assert fake.prompts[0].startswith("[문장 1] <w1>눈</w1>이 온다.\n앞 문장: 날씨가 좋다.")
    other = Judge(Fake(pick(analyzer.analyze(text), False), model="other"), tmp_path)  # 공급자 설정이 다르면 새로 부른다
    assert other.resolve(analyzer.analyze(text)).render() == "진심으로 사과했다." and other.calls == 1


def test_bad_cache_is_miss(analyzer, tmp_path):
    text = "진심으로 사과했다."
    Judge(Fake(pick(analyzer.analyze(text), True)), tmp_path).resolve(analyzer.analyze(text))
    (path,) = tmp_path.iterdir()
    for broken in ["{", '{"answers": {}}', '{"answers": {"1": [7, ""]}}']:
        path.write_text(broken, "utf-8")
        judge = Judge(Fake(pick(analyzer.analyze(text), True)), tmp_path)
        assert judge.resolve(analyzer.analyze(text)).render() == "진심으로 사ː과했다." and judge.calls == 1


def test_cache_write_failure(analyzer, tmp_path, monkeypatch):
    blocked = tmp_path / "file"
    blocked.write_text("", "utf-8")  # 캐시 폴더 자리에 파일이 있어 만들 수 없다
    r = analyzer.analyze("하늘에서 눈이 내린다.")
    Judge(Fake(pick(r, True)), blocked).resolve(r)
    assert r.render() == "하늘에서 눈ː이 내린다."

    def deny(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr("core.judge.os.replace", deny)  # 파일 교체 실패: 결과는 쓰고 임시 파일은 남기지 않는다
    r = analyzer.analyze("하늘에서 눈이 내린다.")
    Judge(Fake(pick(r, True)), tmp_path / "cache").resolve(r)
    assert r.render() == "하늘에서 눈ː이 내린다." and not any((tmp_path / "cache").iterdir())


def test_surrogates(analyzer, tmp_path):
    r = analyzer.analyze("방화 혐의로 체포됐다.")
    Judge(Fake(lambda p: [ans(1, 1, "방화", 1, "불\ud83d")]), tmp_path).resolve(r)
    assert r.items[0].status in ("long", "short") and "\ud83d" not in r.items[0].reason
    r = analyzer.analyze("방화\ud800 혐의로 체포됐다.")
    Judge(Fake(lambda p: [ans(1, 1, "방화", 1)]), tmp_path).resolve(r)
    assert r.items[0].method == "llm" and len(list(tmp_path.glob("*.json"))) == 2


@pytest.mark.parametrize("answer, reason, cached", [
    (lambda p: [ans(1, 1, "방화", None, "모호함")], "판별 필요: LLM이 문맥으로 정하지 못함(모호함)", True),
    (lambda p: LLMError("API 오류 429"), "판별 필요: LLM 호출 실패(API 오류 429)", False),
    (lambda p: "not json", "판별 필요: LLM 호출 실패(응답 형식 오류)", False),
    (lambda p: [ans(1, 1, "방화", 9)], "판별 필요: LLM 응답에 이 단어의 올바른 답이 없음", False),
    (lambda p: [ans(1, True, "방화", 1)], "판별 필요: LLM 응답에 이 단어의 올바른 답이 없음", False),
    (lambda p: [ans(1, 1, "혐의", 1)], "판별 필요: LLM 응답에 이 단어의 올바른 답이 없음", False),  # 번호가 밀린 답
    (lambda p: [{"sentence": 1, "word": 1, "text": "방화", "reason": ""}], "판별 필요: LLM 응답에 이 단어의 올바른 답이 없음", False),
])
def test_stay_undecided(analyzer, tmp_path, answer, reason, cached):
    r = analyzer.analyze("방화 혐의로 체포됐다.")
    Judge(Fake(answer), tmp_path).resolve(r)
    assert [(it.lemma, it.reason) for it in r.undecided] == [("방화", reason)]
    assert any(tmp_path.iterdir()) == cached  # 「정하지 못함」도 올바른 답이라 캐시하고, 실패는 캐시하지 않는다


def test_partial_answer(analyzer, tmp_path):
    r = analyzer.analyze("눈이 오면 눈을 감는다.")
    Judge(Fake(lambda p: [ans(1, 2, "눈", 1)]), tmp_path).resolve(r)
    assert [it.status for it in r.items if it.lemma == "눈"] == ["undecided", "short"]
    assert not any(tmp_path.iterdir())


def gemini(handler):
    return Gemini(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def body(text):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]}


def test_gemini_errors_become_llmerror():
    assert gemini(lambda r: httpx.Response(200, json=body('{"answers": []}')))("s", "p", {}) == '{"answers": []}'
    def error(code):
        return lambda r: httpx.Response(code, json={"error": {"code": code, "message": "x", "status": "X"}})

    for handler, message, stop in [
        (error(429), "API 오류 429", True),
        (error(503), "API 오류 503", True),
        (error(400), "API 오류 400", False),  # 요청 내용 탓: 다음 요청은 보낸다
        (error(401), "API 오류 401", True),
        (error(403), "API 오류 403", True),
        (error(404), "API 오류 404", True),   # 모델 이름 오류
        (lambda r: httpx.Response(400, json={"error": {"code": 400, "message": "API key not valid.", "status": "X"}}),
         "API 오류 400", True),
        (lambda r: httpx.Response(200, text="<html>portal</html>"), "JSONDecodeError", True),
        (lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "OTHER"}}), "빈 응답 .*OTHER", False),
    ]:
        with pytest.raises(LLMError, match=message) as e:
            gemini(handler)("s", "p", {})
        assert e.value.stop is stop

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    calls = []
    with pytest.raises(LLMError, match="ReadTimeout") as e:
        gemini(lambda r: calls.append(r) or timeout(r))("s", "p", {})
    assert len(calls) == 1 and e.value.stop  # 다시 보내지 않는다


# 실제 호출(기준 문장 표의 기대값). JANGDAN_LIVE_LLM=1일 때만 돌리고, 응답은 .cache/llm에 남는다.
LIVE = [
    ("하늘에서 눈이 내린다.", "하늘에서 눈ː이 내린다."),
    ("눈을 감았다.", "눈을 감았다."),
    ("말을 타고 달렸다.", "말을 타고 달렸다."),
    ("말을 잘한다.", "말ː을 잘한다."),
    ("사과를 먹었다.", "사과를 먹었다."),
    ("진심으로 사과했다.", "진심으로 사ː과했다."),
    ("방화 혐의로 체포됐다.", "방ː화 혐의로 체포됐다."),
    ("방화 설비를 점검했다.", "방화 설비를 점검했다."),
    ("칼을 숫돌에 가니 날이 섰다.", "칼을 숫돌에 가ː니 날이 섰다."),
    ("소매를 걷어 올렸다.", "소매를 걷어 올렸다."),
    ("그날밤 비가 왔다.", "그날밤 비가 왔다."),
    ("길을 묻는 사람", "길을 묻ː는 사ː람"),
]


@pytest.mark.skipif(not os.environ.get("JANGDAN_LIVE_LLM"), reason="실제 LLM 호출: JANGDAN_LIVE_LLM=1")
@pytest.mark.parametrize("text, rendered", LIVE)
def test_live(analyzer, text, rendered):
    from core.llm import from_env
    backend = from_env()
    assert backend is not None, "GEMINI_API_KEY 없음"
    r = Judge(backend).resolve(analyzer.analyze(text))
    assert r.render() == rendered and not r.undecided
