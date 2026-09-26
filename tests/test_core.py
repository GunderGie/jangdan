import pytest

from core.lexicon import long_syllables
from prep.build import DB_PATH

# (문장, 장음 표시 결과, 판별 필요 원형). 기대값은 기준 문장 표와 사전 산출물(data/jangdan.sqlite)로 확인했다.
REFERENCE = [
    ("하늘에서 눈이 내린다.", "하늘에서 눈이 내린다.", ["눈"]),
    ("눈을 감았다.", "눈을 감았다.", ["눈"]),
    ("말을 타고 달렸다.", "말을 타고 달렸다.", ["말"]),
    ("말을 잘한다.", "말을 잘한다.", ["말"]),
    ("사과를 먹었다.", "사과를 먹었다.", ["사과"]),
    ("진심으로 사과했다.", "진심으로 사과했다.", ["사과"]),
    ("방화 혐의로 체포됐다.", "방화 혐의로 체포됐다.", ["방화"]),
    ("방화 설비를 점검했다.", "방화 설비를 점검했다.", ["방화"]),
    ("그 사실을 압니다.", "그 사ː실을 압ː니다.", []),
    ("그 사실을 알았다.", "그 사ː실을 알았다.", []),
    ("없어서 못 산다.", "없ː어서 못ː 산ː다.", []),
    ("짐을 끌어 옮겼다.", "짐을 끌ː어 옮겼다.", []),
    ("사람이 많아 보인다.", "사ː람이 많ː아 보인다.", []),
    ("고기를 삶아 먹었다.", "고기를 삶아 먹었다.", []),
    ("버튼을 눌러 주세요.", "버튼을 눌ː러 주세요.", []),
    ("과일을 사는 사람", "과ː일을 사는 사ː람", []),
    ("칼을 숫돌에 가니 날이 섰다.", "칼을 숫돌에 가니 날이 섰다.", ["갈다"]),
    ("학교에 가니 아무도 없었다.", "학교에 가니 아ː무도 없ː었다.", []),
    ("결과를 봐서 정하자.", "결과를 봐ː서 정ː하자.", []),
    ("첫눈이 내렸다.", "첫눈이 내렸다.", []),
    ("공원을 걸어 다녔다.", "공원을 걸어 다녔다.", []),
    ("소매를 걷어 올렸다.", "소매를 걷어 올렸다.", ["소매"]),
]


def test_long_syllables():
    assert long_syllables("반ː신바ː늬") == [0, 2]
    assert long_syllables("되ː다/뒈ː다") == [0]
    assert long_syllables("사과") == []


@pytest.fixture(scope="module")
def analyzer():
    if not DB_PATH.exists():
        pytest.skip("data/jangdan.sqlite 없음: python -m prep.build")
    from core.analyze import Analyzer
    return Analyzer()


def item(analysis, surface):
    found = [it for it in analysis.items if it.surface == surface]
    assert found, f"항목 없음: {surface}"
    return found[0]


@pytest.mark.parametrize("text, rendered, undecided", REFERENCE)
def test_reference(analyzer, text, rendered, undecided):
    r = analyzer.analyze(text)
    assert r.render() == rendered
    assert [it.lemma for it in r.undecided] == undecided


@pytest.mark.xfail(strict=True, reason="Kiwi가 -는 앞 ㄹ 탈락형을 ㄹ 없는 용언(사다)으로 분석함. 기획안 10절 2026-09-26 00:22")
def test_reference_known_failure(analyzer):
    assert analyzer.analyze("서울에 사는 사람").render() == "서울에 사ː는 사ː람"


def test_evidence(analyzer):
    it = item(analyzer.analyze("사람이 많아 보인다."), "많아")
    assert (it.status, it.method, it.conj_pron) == ("long", "rule", "마ː나") and "제7항 예외" in it.reason
    it = item(analyzer.analyze("고기를 삶아 먹었다."), "삶아")
    assert (it.status, it.method, it.conj_pron) == ("short", "rule", "살마") and it.reason.startswith("제7항:")
    it = item(analyzer.analyze("사과를 먹었다."), "먹었다")
    assert (it.status, it.method) == ("short", "dictionary")  # 원래 단음이면 제7항을 근거로 들지 않는다
    assert "제6항 [붙임]" in item(analyzer.analyze("결과를 봐서 정하자."), "봐서").reason
    it = item(analyzer.analyze("공원을 걸어 다녔다."), "걸어")
    assert (it.regularity, it.chosen.source, it.chosen.source_id) == ("불규칙", "krdict", "29667")  # 걷다(步)
    assert it.chosen.link.endswith("ParaWordNo=29667")
    it = item(analyzer.analyze("사과를 먹었다."), "사과")
    assert {c.origin for c, _ in it.candidates} == {"沙果/砂果", "謝過"}
    it = item(analyzer.analyze("버튼을 눌러 주세요."), "버튼")
    assert (it.status, it.reason) == ("unknown", "발음 정보 없음")


@pytest.mark.parametrize("text, rendered", [
    ("회사사람들이 왔다.", "회ː사사람들이 왔다."),   # 제6항 첫음절 원칙, 와는 줄어도 단음
    ("눈사람을 만들었다.", "눈ː사람을 만들었다."),   # 등재 합성어는 사전 발음
    ("사과나무를 심었다.", "사과나무를 심었다."),     # 붙여 쓴 합성어를 먼저 찾아 사과(혼재)로 빠지지 않음
    ("물이 괘 있다.", "물이 괘ː 있다."),             # 제6항 [붙임]
    ("날이 개서 좋다.", "날이 개ː서 좋ː다."),         # 같은 모음이 탈락해 한 음절로 줄어도 장음 유지
    ("\"사람이 많다\"고 했다.", "\"사ː람이 많ː다\"고 했ː다."),  # 어절 앞 문장부호는 건너뜀, 하여→해
])
def test_rules(analyzer, text, rendered):
    assert analyzer.analyze(text).render() == rendered


# 코드 리뷰에서 찾은 오류 유형
@pytest.mark.parametrize("text, rendered, undecided", [
    ("침대에 누워 쉬었다.", "침ː대에 누워 쉬었다.", []),   # ㅂ 불규칙: 축약이 아니라 제7항
    ("집을 지어 살았다.", "집을 지어 살았다.", []),        # ㅅ 불규칙
    ("고기를 구워 먹었다.", "고기를 구워 먹었다.", []),
    ("길을 묻는 사람", "길을 묻는 사ː람", ["묻다"]),       # 자음 어미형으로 동형어를 좁히지 않음
    ("할 수 있다.", "할 수 있다.", []),                    # 의존 명사는 의존 명사 항목을 먼저 봄
    ("그날밤 비가 왔다.", "그날밤 비가 왔다.", ["비"]),    # 첫음절 원칙이 혼재 판정보다 먼저
    ("사람,돈,시간", "사ː람,돈ː,시간", []),               # 문장부호 다음도 어절 첫머리
])
def test_review_cases(analyzer, text, rendered, undecided):
    r = analyzer.analyze(text)
    assert r.render() == rendered
    assert [it.lemma for it in r.undecided] == undecided


def test_sentence_numbers_with_leading_blank_lines(analyzer):
    r = analyzer.analyze("\n\n오늘의 뉴스입니다. 사람이 많습니다.")
    assert len(r.sentences) == 2
    for it in r.items:
        s, e = r.sentences[it.sentence]
        assert s <= it.start and it.end <= e, it.surface


def test_rule_edges_after_rereview(analyzer):
    it = item(analyzer.analyze("먹고사니 바쁘다."), "사니")
    assert it.status == "short" and it.note is None  # 첫음절 원칙으로 단음이면 C안 탓으로 설명하지 않음
    assert analyzer.analyze("가지 마.").render() == "가지 마."  # ㄹ 탈락 뒤 줄어든 형태는 제7항(말아[마라])


def test_conj_pron_matches_pos(analyzer):
    assert item(analyzer.analyze("머리가 검어 보였다."), "검어").conj_pron == "거머"  # 형용사 행만
    it = item(analyzer.analyze("조개를 쪄 먹었다."), "쪄")
    assert it.status == "short" and "다름" in it.note  # 표준은 찌다02 쪄[쩌ː], C안 후보(기초)는 단음


def test_lookups_prefetched(analyzer):
    """원격 DB를 위해 원고 하나의 사전 조회를 한 번에 모은다: 항목 1회, 활용 발음 1회."""
    from core.analyze import Analyzer
    from core.lexicon import Lexicon
    lex, sqls = Lexicon(), []
    query = lex._query
    lex._query = lambda sql, args=(): sqls.append(sql) or query(sql, args)
    text = " ".join(t for t, _, _ in REFERENCE) + " 회사사람들이 왔다. 사과나무를 심었다. 너무 조용해서 행복했다."
    a = Analyzer(lex, analyzer.kiwi)
    rendered = a.analyze(text).render()
    assert len(sqls) == 2 and rendered == analyzer.analyze(text).render()
    forms, _ = a._lookups(a.kiwi.tokenize("사람" * 500))  # 붙여 쓴 명사는 사전의 가장 긴 표기(16자)까지만 잇는다
    assert max(map(len, forms)) <= 16 and len(forms) < 20


def test_max_form_matches_db(analyzer):
    from core.analyze import MAX_FORM
    assert analyzer.lex._query("select max(length(form)) from entry") == [(MAX_FORM,)]  # DB를 다시 만들면 함께 고친다


def test_prefetch_chunks(analyzer, monkeypatch):
    from core.analyze import Analyzer
    from core.lexicon import Lexicon
    monkeypatch.setattr("core.lexicon.CHUNK", 2)
    text = "하늘에서 눈이 내린다. 그 사실을 압니다. 사람이 많아 보인다. 서울에 사는 사람"
    a = Analyzer(Lexicon(), analyzer.kiwi)
    assert a.analyze(text).to_dict() == analyzer.analyze(text).to_dict()
    assert a.lex.entries("") == ()


def test_to_dict_and_threads(analyzer):
    import json
    import threading
    d = analyzer.analyze("사람이 많아 보인다. 눈이 내린다.").to_dict()
    assert [s["text"] for s in d["sentences"]] == ["사람이 많아 보인다.", "눈이 내린다."]
    assert json.loads(json.dumps(d, ensure_ascii=False))["rendered"] == "사ː람이 많ː아 보인다. 눈이 내린다."
    out = []
    th = threading.Thread(target=lambda: out.append(analyzer.analyze("그 사실을 압니다.").render()))
    th.start()
    th.join()
    assert out == ["그 사ː실을 압ː니다."]
