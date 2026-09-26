"""조회용 DB에서 사전 항목, 제7항 예외, 표준국어대사전 활용 발음을 찾는다."""
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from prep.build import DB_PATH

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


class Lexicon:
    """읽기 전용 연결 하나를 여러 스레드가 나눠 쓴다(API 서버의 스레드 풀)."""

    def __init__(self, db_path=DB_PATH):
        if not Path(db_path).exists():
            raise FileNotFoundError(f"DB 없음: {db_path} (python -m prep.build 먼저)")
        self.con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        self._lock = threading.Lock()
        self._cache = {}
        self.keep7 = {(lemma, p) for lemma, pos in self._query("select lemma, pos from rule7_keep")
                      for p in pos.split("/")}

    def _query(self, sql, args=()):
        with self._lock:
            return self.con.execute(sql, args).fetchall()

    def entries(self, form):
        if form not in self._cache:
            rows = self._query(
                "select source, source_id, headword, homonym_no, pos, origin, pron, is_long, senses, conj "
                "from entry where form = ? order by id", (form,))
            self._cache[form] = tuple(
                Candidate(s, sid, hw, hn or 0, pos or "", origin or "", pron,
                          None if il is None else bool(il),
                          tuple(tuple(x) for x in json.loads(senses)) if senses else (),
                          tuple((c[0], tuple(c[1]), c[2]) for c in json.loads(conj)) if conj else ())
                for s, sid, hw, hn, pos, origin, pron, il, senses, conj in rows)
        return self._cache[form]

    def keeps_long(self, lemma, pos_parts):
        """제7항 예외: 모음 어미 앞에서도 장음을 유지하는가(표준국어대사전 활용 발음 기준)."""
        return any((lemma, p) in self.keep7 for p in pos_parts)

    def conj_pron(self, lemma, surface, pos_parts):
        """표준국어대사전 웹에서 수집한 활용 발음 가운데 품사가 맞는 것(단음절 장음 용언만). 예: (많다, 많아) → 마ː나"""
        prons = sorted({pron for pos, pron in self._query(
            "select pos, pron from conj_pron where lemma = ? and form = ?", (lemma, surface))
            if set(pos.split("/")) & pos_parts})
        return "/".join(prons) or None
