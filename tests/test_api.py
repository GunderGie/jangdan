import json

import pytest
from fastapi.testclient import TestClient

from core.judge import Judge
from prep.build import DB_PATH


class Fake:
    """문장 1의 단어 1에 장음 후보를 답하는 공급자."""
    model = id = "fake"

    def __init__(self):
        self.calls = 0

    def __call__(self, system, prompt, schema):
        self.calls += 1
        return json.dumps({"answers": [{"sentence": 1, "word": 1, "text": "눈", "choice": 4, "reason": "하늘에서 내림"}]})


@pytest.fixture(scope="module")
def analyzer():
    if not DB_PATH.exists():
        pytest.skip("data/jangdan.sqlite 없음: python -m prep.build")
    from core.analyze import Analyzer
    return Analyzer()


@pytest.fixture
def client(analyzer, tmp_path):
    from api.main import create_app
    fake = Fake()
    return TestClient(create_app(analyzer, Judge(fake, tmp_path))), fake


def test_analyze(client):
    c, fake = client
    body = c.post("/api/analyze", json={"text": "하늘에서 눈이 내린다. 사람이 많다."}).json()
    assert body["rendered"] == "하늘에서 눈ː이 내린다. 사ː람이 많ː다."
    assert body["meta"]["llm"] == "fake" and fake.calls == 1
    snow = next(it for it in body["items"] if it["lemma"] == "눈")
    assert (snow["method"], snow["chosen"]["homonym_no"], len(snow["candidates"])) == ("llm", 4, 5)
    person = next(it for it in body["items"] if it["lemma"] == "사람")
    assert person["candidates"] == [] and person["chosen"]["link"].startswith("https://krdict")  # 후보 목록은 줄이고 근거는 남긴다


def test_without_llm(client):
    c, fake = client
    body = c.post("/api/analyze", json={"text": "하늘에서 눈이 내린다.", "llm": False}).json()
    snow = next(it for it in body["items"] if it["lemma"] == "눈")
    assert (snow["status"], body["meta"]["llm"], fake.calls) == ("undecided", None, 0)
    assert len(snow["candidates"]) == 5


@pytest.mark.parametrize("text", ["", "가" * 2001], ids=["empty", "2001chars"])
def test_text_length(client, text):
    r = client[0].post("/api/analyze", json={"text": text})
    assert r.status_code == 422 and "가가" not in r.text  # 입력을 되돌려 주지 않는다


def test_bad_input(client):
    c = client[0]
    r = c.post("/api/analyze", content='{"text": "\\ud800 사람"}', headers={"content-type": "application/json"})
    assert r.status_code == 422  # 짝 없는 서로게이트: 기본 처리기는 입력을 되돌려 주다 500을 냈다
    r = c.post("/api/analyze", content="{" + " " * 70_000 + "}", headers={"content-type": "application/json"})
    assert r.status_code == 413
    chunks = iter([b'{"text": "', b"\xea\xb0\x80" * 30_000, b'"}'])  # 크기를 미리 알 수 없는 chunked 본문
    r = c.post("/api/analyze", content=chunks, headers={"content-type": "application/json"})
    assert r.status_code == 411


def test_db_error(analyzer, tmp_path):
    import sqlite3
    from api.main import create_app
    from core.analyze import Analyzer
    from core.lexicon import Lexicon

    class Broken:
        def execute(self, *args):
            raise sqlite3.OperationalError("disk I/O error")

    lex = Lexicon()
    lex.con = Broken()
    c = TestClient(create_app(Analyzer(lex, analyzer.kiwi), Judge(Fake(), tmp_path)))
    r = c.post("/api/analyze", json={"text": "사람이 많다."})
    assert (r.status_code, r.json()) == (503, {"detail": "local DB 조회 실패"})
