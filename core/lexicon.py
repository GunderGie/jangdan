"""조회용 DB에서 사전 항목, 제7항 예외, 표준국어대사전 활용 발음을 찾는다. DB는 로컬 파일이나 Turso를 쓴다."""
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from prep.build import DB_PATH
from prep.dicts import ROOT

ENTRY_SQL = ("select form, source, source_id, headword, homonym_no, pos, origin, pron, is_long, senses, conj "
             "from entry where form in ({}) order by id")
CONJ_SQL = "select lemma, form, pos, pron from conj_pron where lemma in ({})"
CHUNK = 200  # IN 목록 한 번의 크기
MAX_CACHE = 100_000  # 캐시한 표기 수가 이보다 많아지면 비운다(서버 메모리)


class LexiconError(Exception):
    """DB 조회 실패(Turso 인증·연결 오류 등)."""

LINKS = {
    "krdict": "https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo={}",
    "stdict": "https://stdict.korean.go.kr/search/searchView.do?word_no={}&searchKeywordTo=3",
}


def long_syllables(pron):
    """발음에서 장음 음절의 위치(0부터). 이형이 여럿이면 첫 이형을 본다. 예: 반ː신바ː늬 → [0, 2]"""
    out, i = [], -1
    for ch in (pron or "").split("/")[0]:
        if ch == "ː":
            out.append(i)
        else:
            i += 1
    return out


@dataclass(frozen=True)
class Candidate:
    source: str
    source_id: str
    headword: str
    homonym_no: int
    pos: str
    origin: str
    pron: str | None
    is_long: bool | None
    senses: tuple   # ((품사, 뜻풀이), ...)
    conj: tuple     # ((표기, (발음, ...), 활용|준말), ...)

    @property
    def pos_parts(self):
        return set(self.pos.split("/")) if self.pos else set()

    @property
    def link(self):
        return LINKS[self.source].format(self.source_id)

    def definition(self, pos_names=()):
        """품사가 맞는 첫 뜻풀이. 없으면 첫 뜻풀이."""
        for p, d in self.senses:
            if p in pos_names:
                return d
        return self.senses[0][1] if self.senses else ""

    def conj_forms(self):
        return {c[0] for c in self.conj}

    def to_dict(self, pos_names=()):
        return {"source": self.source, "source_id": self.source_id, "headword": self.headword,
                "homonym_no": self.homonym_no, "pos": self.pos, "origin": self.origin, "pron": self.pron,
                "definition": self.definition(pos_names), "link": self.link}


def _candidate(row):
    s, sid, hw, hn, pos, origin, pron, il, senses, conj = row
    return Candidate(s, sid, hw, hn or 0, pos or "", origin or "", pron, None if il is None else bool(il),
                     tuple(tuple(x) for x in json.loads(senses)) if senses else (),
                     tuple((c[0], tuple(c[1]), c[2]) for c in json.loads(conj)) if conj else ())


class Lexicon:
    """읽기 전용 연결 하나를 여러 스레드가 나눠 쓴다(API 서버의 스레드 풀).

    원격 DB(Turso)는 조회 한 번에 약 175ms가 걸려서, 분석기가 찾을 표기를 prefetch로 모아 한 번에 조회한다.
    """

    def __init__(self, db_path=DB_PATH, con=None, source="local"):
        if con is None:
            if not Path(db_path).exists():
                raise FileNotFoundError(f"DB 없음: {db_path} (python -m prep.build 먼저)")
            con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        self.con, self.source = con, source
        self._lock = threading.Lock()
        self._cache = {}  # 표기 → 후보
        self._conj = {}   # 원형 → ((활용형, 품사, 발음), ...)
        self.keep7 = {(lemma, p) for lemma, pos in self._query("select lemma, pos from rule7_keep")
                      for p in pos.split("/")}

    @classmethod
    def from_env(cls):
        """.env의 JANGDAN_DB_SOURCE가 turso면 Turso(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN), 아니면 로컬 파일을 쓴다."""
        load_dotenv(ROOT / ".env")
        source = (os.environ.get("JANGDAN_DB_SOURCE") or "local").strip().lower()
        if source == "local":
            return cls()
        if source != "turso":
            raise ValueError(f"JANGDAN_DB_SOURCE는 local 또는 turso: {source!r}")
        missing = [k for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN") if not os.environ.get(k)]
        if missing:
            raise ValueError(f"Turso를 쓰려면 .env에 {', '.join(missing)}가 필요하다")
        if not os.environ["TURSO_DATABASE_URL"].startswith(("libsql://", "https://", "wss://")):
            raise ValueError("TURSO_DATABASE_URL은 libsql://로 시작해야 한다(아니면 libsql이 로컬 파일로 연다)")
        import libsql
        return cls(con=libsql.connect(os.environ["TURSO_DATABASE_URL"], auth_token=os.environ["TURSO_AUTH_TOKEN"],
                                      _check_same_thread=False), source="turso")

    def _query(self, sql, args=()):
        try:
            with self._lock:
                return self.con.execute(sql, args).fetchall()
        except (sqlite3.Error, ValueError) as e:  # libsql은 원격 오류를 ValueError로 낸다
            raise LexiconError(f"{self.source} DB 조회 실패") from e

    def prefetch(self, forms=(), lemmas=()):
        """표기의 사전 항목과 원형의 활용 발음을 모아 한 번에 조회해 둔다."""
        for cache in (self._cache, self._conj):
            if len(cache) > MAX_CACHE:
                cache.clear()
        forms = sorted({f for f in forms if f and f not in self._cache})
        for i in range(0, len(forms), CHUNK):
            part = forms[i:i + CHUNK]
            found = {}
            for row in self._query(ENTRY_SQL.format(",".join("?" * len(part))), part):
                found.setdefault(row[0], []).append(_candidate(row[1:]))
            for f in part:
                self._cache[f] = tuple(found.get(f, ()))
        lemmas = sorted({x for x in lemmas if x and x not in self._conj})
        for i in range(0, len(lemmas), CHUNK):
            part = lemmas[i:i + CHUNK]
            found = {}
            for lemma, form, pos, pron in self._query(CONJ_SQL.format(",".join("?" * len(part))), part):
                found.setdefault(lemma, []).append((form, pos, pron))
            for x in part:
                self._conj[x] = tuple(found.get(x, ()))

    def entries(self, form):
        if form not in self._cache:
            self.prefetch(forms=[form])
        return self._cache.get(form, ())

    def keeps_long(self, lemma, pos_parts):
        """제7항 예외: 모음 어미 앞에서도 장음을 유지하는가(표준국어대사전 활용 발음 기준)."""
        return any((lemma, p) in self.keep7 for p in pos_parts)

    def conj_pron(self, lemma, surface, pos_parts):
        """표준국어대사전 웹에서 수집한 활용 발음 가운데 품사가 맞는 것(단음절 장음 용언만). 예: (많다, 많아) → 마ː나"""
        if lemma not in self._conj:
            self.prefetch(lemmas=[lemma])
        prons = sorted({pron for form, pos, pron in self._conj.get(lemma, ())
                        if form == surface and set(pos.split("/")) & pos_parts})
        return "/".join(prons) or None
