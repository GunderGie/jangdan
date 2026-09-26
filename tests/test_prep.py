import sqlite3

import pytest

from prep import build, dicts, rule7, stats

KR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<LexicalResource><Lexicon>
<LexicalEntry att="id" val="1">
  <feat att="homonym_number" val="2" /><feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="명사" />
  <Lemma><feat att="writtenForm" val="사과" /></Lemma><feat att="origin" val="謝過" />
  <WordForm><feat att="type" val="발음" /><feat att="pronunciation" val=" 사:과 " /></WordForm>
  <Sense att="id" val="1"><feat att="definition" val="잘못을 빎.\x08" />
    <SenseExample><feat att="type" val="대화" /><feat att="example" val="가" /><feat att="example" val="나" /></SenseExample>
  </Sense>
</LexicalEntry>
<LexicalEntry att="id" val="2">
  <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="동사" />
  <Lemma><feat att="writtenForm" val="하다" /></Lemma>
  <WordForm><feat att="type" val="발음" /><feat att="pronunciation" val="하다" /></WordForm>
  <WordForm><feat att="type" val="활용" /><feat att="writtenForm" val="하여 " /><feat att="pronunciation" val="하여" />
    <FormRepresentation><feat att="type" val="준말" /><feat att="writtenForm" val="해" /><feat att="pronunciation" val="해ː" /></FormRepresentation>
  </WordForm>
</LexicalEntry>
<LexicalEntry att="id" val="3">
  <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="어미" /><Lemma><feat att="writtenForm" val="-매" /></Lemma>
</LexicalEntry>
<LexicalEntry att="id" val="4">
  <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="어미" /><Lemma><feat att="writtenForm" val="로구만" /></Lemma>
</LexicalEntry>
<LexicalEntry att="id" val="5">
  <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="명사" /><Lemma><feat att="writtenForm" val="변이" /></Lemma>
  <WordForm><feat att="type" val="발음" /><feat att="pronunciation" val="變異" /></WordForm>
</LexicalEntry>
<LexicalEntry att="id" val="6">
  <feat att="lexicalUnit" val="구" /><Lemma><feat att="writtenForm" val="눈이 높다" /></Lemma>
</LexicalEntry>
</Lexicon></LexicalResource>
"""

STD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<channel>
<item><target_code>100</target_code><word_info><word>사과02</word><word_unit>단어</word_unit>
  <original_language_info><original_language>角觝</original_language><language_type>한자</language_type></original_language_info>
  <original_language_info><original_language>/</original_language><language_type>/(병기)</language_type></original_language_info>
  <original_language_info><original_language>角抵</original_language><language_type>한자</language_type></original_language_info>
  <pronunciation_info><pronunciation>사:과</pronunciation></pronunciation_info>
  <conju_info><conjugation_info><conjugation>사과하여</conjugation></conjugation_info>
    <abbreviation_info><abbreviation>사과해</abbreviation></abbreviation_info></conju_info>
  <pos_info><pos>명사</pos><comm_pattern_info><sense_info><definition>뜻1</definition>
    <example_info><example>예문1</example><source>누구, 책</source></example_info></sense_info></comm_pattern_info></pos_info>
  <pos_info><pos>부사</pos><comm_pattern_info><sense_info><definition>뜻2</definition></sense_info></comm_pattern_info></pos_info>
</word_info></item>
<item><target_code>101</target_code><word_info><word>각-사탕</word><word_unit>단어</word_unit>
  <pronunciation_info><pronunciation>각싸탕/각사탕</pronunciation></pronunciation_info></word_info></item>
<item><target_code>102</target_code><word_info><word>간-15</word><word_unit>단어</word_unit><pos_info><pos>접사</pos></pos_info></word_info></item>
<item><target_code>103</target_code><word_info><word>가는^귀</word><word_unit>단어</word_unit><pos_info><pos>명사</pos></pos_info></word_info></item>
<item><target_code>104</target_code><word_info><word>눈이^높다</word><word_unit>구</word_unit></word_info></item>
<item><target_code>105</target_code><word_info><word>디02</word><word_unit>단어</word_unit>
  <original_language_info><original_language>D</original_language><language_type>영어</language_type></original_language_info>
  <original_language_info><original_language>/</original_language><language_type>/(병기)</language_type></original_language_info>
  <original_language_info><original_language>d</original_language><language_type>영어</language_type></original_language_info>
  <pronunciation_info><pronunciation>ː디</pronunciation></pronunciation_info></word_info></item>
</channel>
"""


@pytest.fixture
def raw(tmp_path):
    for sub, text in ((dicts.KRDICT_DIR, KR_XML), (dicts.STDICT_DIR, STD_XML)):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "1.xml").write_text(text, encoding="utf-8")
    return tmp_path


def test_read_krdict(raw):
    es = {e.source_id: e for e in dicts.read_krdict(raw)}
    assert set(es) == {"1", "2", "3", "4", "5"}
    a = es["1"]
    assert (a.form, a.homonym_no, a.pos, a.prons, a.is_long, a.bound) == ("사과", 2, "명사", ["사ː과"], True, False)
    assert a.senses == [("명사", "잘못을 빎.")]
    assert a.examples == [(1, "대화", "가\n나", None)]
    assert es["2"].conj == [("하여", ["하여"], "활용"), ("해", ["해ː"], "준말")]
    assert es["3"].bound and es["4"].bound
    assert (es["5"].prons, es["5"].bad_prons, es["5"].is_long) == ([], ["變異"], None)
    assert [e.prons for e in dicts.read_krdict(raw, strict=False) if e.source_id == "5"] == [["變異"]]


def test_read_stdict(raw):
    es = {e.source_id: e for e in dicts.read_stdict(raw)}
    assert set(es) == {"100", "101", "102", "103", "105"}
    assert es["103"].form == "가는귀"
    assert (es["105"].origin, es["105"].prons, es["105"].bad_prons) == ("", [], ["ː디"])
    a = es["100"]
    assert (a.form, a.homonym_no, a.pos, a.origin, a.prons) == ("사과", 2, "명사/부사", "角觝/角抵", ["사ː과"])
    assert a.senses == [("명사", "뜻1"), ("부사", "뜻2")]
    assert a.examples == [(1, None, "예문1", "누구, 책")]
    assert a.conj == [("사과하여", [], "활용"), ("사과해", [], "준말")]
    assert (es["101"].form, es["101"].bound, es["101"].prons) == ("각사탕", False, ["각싸탕", "각사탕"])
    assert (es["102"].form, es["102"].bound) == ("간-", True)


def test_build_small(raw, tmp_path):
    db = tmp_path / "t.sqlite"
    build.build(db, raw)
    con = sqlite3.connect(db)
    sources = dict(con.execute("select form, group_concat(source) from entry group by form"))
    con.close()
    assert sources == {"사과": "krdict", "하다": "krdict", "변이": "krdict",
                       "각사탕": "stdict", "가는귀": "stdict", "디": "stdict"}


def test_build_keeps_db_when_raw_missing(tmp_path):
    db = tmp_path / "x.sqlite"
    db.write_bytes(b"keep")
    with pytest.raises(FileNotFoundError):
        build.build(db, tmp_path / "없음")
    assert db.read_bytes() == b"keep"
    assert not (tmp_path / "x.tmp").exists()


def test_build_keeps_db_when_no_stdict_words(raw, tmp_path):
    (raw / dicts.STDICT_DIR / "1.xml").write_text(
        '<channel><item><target_code>1</target_code><word_info><word>눈이^높다</word>'
        '<word_unit>구</word_unit></word_info></item></channel>', encoding="utf-8")
    db = tmp_path / "y.sqlite"
    db.write_bytes(b"keep")
    with pytest.raises(RuntimeError):
        build.build(db, raw)
    assert db.read_bytes() == b"keep"
    assert not (tmp_path / "y.tmp").exists()


def test_open_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        stats.open_db(tmp_path / "없음.sqlite")
    assert not (tmp_path / "없음.sqlite").exists()
    p = tmp_path / "a#b %41" / "x.sqlite"
    p.parent.mkdir()
    con = sqlite3.connect(p)
    con.execute("create table meta(key text, value text)")
    con.commit()
    con.close()
    ro = stats.open_db(p)
    assert ro.execute("select count(*) from meta").fetchone()[0] == 0
    ro.close()


def test_rule7_review():
    rows = rule7.load()
    rev = rule7.review(rows)
    assert len(rev) == 41 and all(r["first_long"] for r in rev)
    assert not rule7.inconsistent(rows)
    assert not rule7.key_conflicts(rows)
    assert len(rule7.keep_long(rows)) == 25


# 아래는 실제 빌드 결과(data/jangdan.sqlite)를 본다. 없으면 건너뛴다.
@pytest.fixture(scope="module")
def db():
    if not build.DB_PATH.exists():
        pytest.skip("data/jangdan.sqlite 없음: python -m prep.build")
    con = stats.open_db()
    yield con
    con.close()


def form_class(db, form):
    row = db.execute("select class from form_class where form = ?", (form,)).fetchone()
    assert row, f"form_class에 없음: {form}"
    return row[0]


def test_form_class(db):
    for form in ["눈", "말", "사과", "방화", "걷다", "누르다"]:
        assert form_class(db, form) == "mixed", form
    assert form_class(db, "알다") == "all_long"
    assert form_class(db, "변이") == "nopron"  # 발음 칸에 한자만 있던 기초사전 항목


def test_pron(db):
    assert {r[0] for r in db.execute("select pron from entry where form = '첫눈'")} == {"천눈"}
    assert set(db.execute("select pos, is_long from entry where form = '누르다'")) == {("동사", 1), ("형용사", 0)}


def test_rule7_keep(db):
    lemmas = {r[0] for r in db.execute("select lemma from rule7_keep")}
    assert {"많다", "없다", "끌다"} <= lemmas
    assert not {"삶다", "감다"} & lemmas


def test_entries_are_words_with_source(db):
    assert db.execute("select count(*) from entry where form like '-%' or form like '%-'").fetchone()[0] == 0
    assert db.execute("select count(*) from entry where pos in ('어미', '접사')").fetchone()[0] == 0
    assert db.execute("select count(*) from (select distinct source, source_id from entry)").fetchone()[0] == \
        db.execute("select count(*) from entry").fetchone()[0]


def test_examples(db):
    texts = {r[0] for r in db.execute(
        "select x.text from example x join entry e on e.id = x.entry_id where e.form = '사과하다'")}
    assert "진심으로 사과하다." in texts
    assert db.execute("select count(*) from example where citation is not null").fetchone()[0] > 0
