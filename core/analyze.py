"""원고에서 장음 음절과 근거를 찾는다(기획안 5절 1~5단계와 7단계). LLM 판별(6단계)은 judge.py가 한다.

1. 형태소 분석: Kiwi가 어간을 원형으로 복원하고 원문 위치(start, len)를 준다.
2. 사전 조회: 원형(표기)과 품사로 동형어 후보를 찾는다.
3·4. 3분류와 문법 정보: 품사로 후보를 거르고, 불규칙 활용은 모음 어미형 표기로 동형어를 좁힌다.
5. 규칙: 제6항 첫음절 원칙, 제6항 [붙임] 축약, 제7항 단음화와 그 예외.
"""
import re
from dataclasses import dataclass, field

from jamo import h2j, j2hcj
from kiwipiepy import Kiwi

from .lexicon import Lexicon, long_syllables

# Kiwi 품사 → 사전 품사. 앞 묶음에 맞는 항목이 없을 때만 다음 묶음을 본다.
POS = {"NNG": [("명사",)], "NNP": [("명사",)], "NNB": [("의존 명사",), ("명사",)], "NR": [("수사",)],
       "NP": [("대명사",)], "VV": [("동사",)], "VA": [("형용사",)], "VX": [("보조 동사", "보조 형용사")],
       "MM": [("관형사",)], "MAG": [("부사",)], "MAJ": [("부사",)], "IC": [("감탄사",)]}
XR_POS = {"XSA": [("형용사",)], "XSV": [("동사",)]}  # 어근 + -하다 등은 접미사로 품사를 정한다
VERBS = {"VV", "VA", "VX"}
COMPOUND = {"NNG", "NNP", "XPN"}  # 붙여 쓴 합성어는 이어 붙인 표기를 먼저 찾는다
# 제6항 [붙임]: (어간 모음, 줄어든 음절 모음). 하여→해는 어간이 '하'일 때만 본다.
CONTRACT = {("ㅗ", "ㅘ"), ("ㅜ", "ㅝ"), ("ㅣ", "ㅕ"), ("ㅚ", "ㅙ")}
CONTRACT_SHORT = {("ㅇ", "ㅘ"), ("ㅈ", "ㅕ"), ("ㅉ", "ㅕ"), ("ㅊ", "ㅕ")}  # 와, 져, 쪄, 쳐(다만)


@dataclass
class Item:
    start: int
    end: int
    surface: str
    lemma: str
    tag: str
    sentence: int
    pos_names: tuple
    status: str = ""                                # long | short | undecided | unknown
    reason: str = ""
    method: str | None = None                       # dictionary | rule | llm
    long_positions: list = field(default_factory=list)
    candidates: list = field(default_factory=list)  # [(Candidate, 규칙을 적용한 장음 여부)]
    chosen: object = None                           # Candidate
    regularity: str | None = None                   # Kiwi의 규칙·불규칙 표시(-R/-I)
    conj_pron: str | None = None                    # 표준국어대사전 활용 발음(있을 때)
    note: str | None = None
    stem_len: int | None = None                     # 용언: 원문에 보이는 어간 길이(장음 표시 범위)

    def choose(self, k, method, reason):
        """후보 k(0부터)를 고른 결과로 장단을 정한다(LLM 판별)."""
        c, v = self.candidates[k]
        self.chosen, self.method, self.reason = c, method, reason
        if v is None:
            self.status, self.reason, self.long_positions = "unknown", reason + " / 고른 동형어에 발음 정보 없음", []
        elif v:
            self.status, self.long_positions = "long", Analyzer._positions(self, [(c, v)], self.stem_len)
        else:
            self.status, self.long_positions = "short", []
        if not v:  # 표준국어대사전 활용 발음은 장음 용언만 모았으므로 고른 동형어의 것이 아니다
            self.conj_pron = None
        self.note = _conj_note(self)

    def to_dict(self):
        return {"start": self.start, "end": self.end, "surface": self.surface, "lemma": self.lemma, "tag": self.tag,
                "sentence": self.sentence, "status": self.status, "reason": self.reason, "method": self.method,
                "long_positions": self.long_positions, "regularity": self.regularity, "conj_pron": self.conj_pron,
                "note": self.note, "chosen": self.chosen.to_dict(self.pos_names) if self.chosen else None,
                "candidates": [dict(c.to_dict(self.pos_names), long=v) for c, v in self.candidates]}


@dataclass
class Analysis:
    text: str
    items: list
    sentences: list  # 문장 번호(Item.sentence) 순서의 (start, end)

    @property
    def long_positions(self):
        return sorted(p for it in self.items for p in it.long_positions)

    @property
    def undecided(self):
        return [it for it in self.items if it.status == "undecided"]

    def render(self):
        """장음 음절 뒤에 ː를 넣은 문자열."""
        marks = set(self.long_positions)
        return "".join(ch + ("ː" if i in marks else "") for i, ch in enumerate(self.text))

    def to_dict(self):
        return {"text": self.text, "rendered": self.render(), "long_positions": self.long_positions,
                "sentences": [{"start": s, "end": e, "text": self.text[s:e]} for s, e in self.sentences],
                "items": [it.to_dict() for it in self.items]}


def _jamo(ch):
    """한글 음절 → (초성, 중성, 종성). 음절이 아니면 None."""
    if not ch or not ("가" <= ch <= "힣"):
        return None
    j = j2hcj(h2j(ch))
    return j[0], j[1], j[2:]


def _vowel_initial(form):
    j = _jamo(form[:1])
    return j is not None and j[0] == "ㅇ"


def _conj_note(item):
    """결과가 표준국어대사전 활용 발음의 장단과 다르면 표시한다(어절 첫머리 용언)."""
    if item.conj_pron and item.status in ("long", "short") and ("ː" in item.conj_pron) != (item.status == "long"):
        return "표준국어대사전 활용 발음과 다름(C안에서 기초사전 발음을 따름)"
    return None


class Analyzer:
    def __init__(self, lexicon=None, kiwi=None):
        self.lex = lexicon or Lexicon()
        self.kiwi = kiwi or Kiwi()

    def analyze(self, text):
        toks = self.kiwi.tokenize(text)
        firsts = {m.start() for m in re.finditer(r"\w+", text)}  # 어절 첫머리: 공백·문장부호 다음 글자
        spans = {}
        for t in toks:
            s, e = spans.get(t.sent_position, (t.start, t.start + t.len))
            spans[t.sent_position] = (min(s, t.start), max(e, t.start + t.len))
        items, i = [], 0
        while i < len(toks):
            t = toks[i]
            tag = t.tag.split("-")[0]
            if tag in COMPOUND and (found := self._compound(text, toks, i, firsts)):
                items.append(found[0])
                i = found[1]
                continue
            if tag == "XR":
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and nxt.tag[:3] in XR_POS:
                    items.append(self._word(text, t.start, nxt.start + nxt.len, t.form + nxt.form + "다", "XR",
                                            XR_POS[nxt.tag[:3]], t.sent_position, t.start in firsts))
                    i += 2
                    continue
            elif tag in VERBS:
                items.append(self._verb(text, toks, i, firsts))
            elif tag in POS:
                items.append(self._word(text, t.start, t.start + t.len, t.form, tag, POS[tag], t.sent_position,
                                        t.start in firsts))
            i += 1
        # Kiwi의 문장 번호는 0부터 빈틈없이 매겨진다는 보장이 없다(원고 앞 빈 줄 등). sentences 순서로 다시 매긴다.
        order = {k: n for n, k in enumerate(sorted(spans))}
        for it in items:
            it.sentence = order[it.sentence]
        return Analysis(text, items, [spans[k] for k in sorted(spans)])

    def _compound(self, text, toks, i, firsts):
        """붙여 쓴 명사(접두사 포함)를 이어 붙인 가장 긴 등재 표기. 없으면 None."""
        form, best, j = toks[i].form, None, i
        while j + 1 < len(toks) and toks[j + 1].tag.split("-")[0] in ("NNG", "NNP") \
                and toks[j + 1].start == toks[j].start + toks[j].len:
            j += 1
            form += toks[j].form
            if self.lex.entries(form):
                best = (j, form)
        if best is None:
            return None
        t, last = toks[i], toks[best[0]]
        return self._word(text, t.start, last.start + last.len, best[1], "NNG", POS["NNG"], t.sent_position,
                          t.start in firsts), best[0] + 1

    def _candidates(self, form, groups):
        cands = self.lex.entries(form)
        for g in groups:
            matched = [c for c in cands if c.pos_parts & set(g)]
            if matched:
                return matched
        return list(cands)

    def _keeps(self, c, lemma):
        """제7항 적용 뒤 장음 여부: 원래 장음이고 예외 목록에 있을 때만 장음."""
        return None if c.is_long is None else c.is_long and self.lex.keeps_long(lemma, c.pos_parts)

    def _word(self, text, start, end, form, tag, groups, sent, initial):
        """용언이 아닌 단어: 사전 발음을 따르고, 어절 첫머리가 아니면 제6항 첫음절 원칙으로 단음."""
        names = tuple(n for g in groups for n in g)
        item = Item(start, end, text[start:end], form, tag, sent, names)
        cands = self._candidates(form, groups)
        return self._judge(item, [(c, c.is_long) for c in cands], initial, "dictionary", "")

    def _verb(self, text, toks, i, firsts):
        t = toks[i]
        tag = t.tag.split("-")[0]
        lemma = t.lemma or t.form + "다"
        stem = lemma[:-1]
        ends = []
        for u in toks[i + 1:]:
            if not u.tag.startswith("E"):
                break
            ends.append(u)
        end = max([t.start + t.len] + [u.start + u.len for u in ends])
        surface = text[t.start:end]
        names = tuple(n for g in POS[tag] for n in g)
        cands = self._candidates(lemma, POS[tag])
        nxt = ends[0] if ends else None
        single = len(stem) == 1
        lengths = [(c, c.is_long) for c in cands]
        method, reason, handled = "dictionary", "", False
        # 제6항 [붙임]: 어간과 -아/-어(-았/-었)가 같은 음절에서 시작하면 한 음절로 준 것이다(봐, 됐, 해).
        if single and nxt is not None and t.len == 1 and nxt.start == t.start and nxt.form[:1] in ("어", "었"):
            s, m = _jamo(stem), _jamo(text[t.start])
            merged = text[t.start]
            if s and m and ((s[1], m[1]) in CONTRACT or (stem == "하" and m[1] == "ㅐ")):
                handled = True
                if (m[0], m[1]) in CONTRACT_SHORT:
                    lengths = [(c, self._keeps(c, lemma)) for c in cands]
                    method, reason = "rule", "제6항 [붙임] 다만: 와·져·쪄·쳐는 줄어도 단음"
                else:
                    lengths = [(c, True) for c in cands]
                    method, reason = "rule", f"제6항 [붙임]: 어간과 어미가 한 음절 「{merged}」로 줄어 장음"
            elif s and m and s[1] == m[1] and not s[2]:  # 받침 없는 어간의 같은 모음 탈락(개어→개): 기본형 장단
                handled = True
                if cands and all(c.is_long for c in cands):
                    method, reason = "rule", f"제6항 [붙임]: 어간과 어미가 한 음절 「{merged}」로 줄어 장음 유지"
        # 제7항: 단음절 어간 + 모음 어미(ㅂ·ㅅ 불규칙의 구워·지어도 여기 해당). 원래 장음일 때만 본다.
        if not handled and nxt is not None and _vowel_initial(nxt.form):
            by_form = [c for c in cands if surface in c.conj_forms()]  # 불규칙: 걸어→걷다 步, 걷어→걷다 捲
            if by_form:
                cands = by_form
                lengths = [(c, c.is_long) for c in cands]
            rdrop_o = nxt.form.startswith("오") and single and _jamo(stem)[2] == "ㄹ" and text[t.start] != stem
            if single and not rdrop_o and any(c.is_long for c in cands):
                lengths = [(c, self._keeps(c, lemma)) for c in cands]
                method = "rule"
                reason = ("제7항 예외: 모음 어미 앞에서도 장음 유지(표준국어대사전 활용 발음)"
                          if any(v for _, v in lengths) else "제7항: 단음절 어간에 모음 어미가 붙어 단음")
        item = Item(t.start, end, surface, lemma, t.tag, t.sent_position, names,
                    regularity={"-R": "규칙", "-I": "불규칙"}.get(t.tag[-2:]))
        item.conj_pron = self.lex.conj_pron(lemma, surface, set().union(*(c.pos_parts for c in cands)))
        initial = t.start in firsts
        item = self._judge(item, lengths, initial, method, reason, stem_len=t.len)
        if initial:
            item.note = _conj_note(item)
        return item

    def _judge(self, item, lengths, initial, method, reason, stem_len=None):
        item.candidates, item.stem_len = lengths, stem_len
        known = {v for _, v in lengths if v is not None}
        if len(lengths) == 1:
            item.chosen = lengths[0][0]
        if not lengths:
            item.status, item.reason = "unknown", "사전에 없음"
        elif not known:
            item.status, item.reason = "unknown", "발음 정보 없음"
        elif known == {False}:
            item.status, item.method = "short", method
            item.reason = reason or self._dict_reason(lengths)
        elif not initial:
            item.status, item.method = "short", "rule"
            item.reason = "제6항 첫음절 원칙: 어절 첫머리가 아니라 장음이 나타나지 않음"
        elif len(known) == 2:
            item.status, item.reason = "undecided", "판별 필요: 동형어의 장단이 섞여 있음"
        else:
            item.status, item.method = "long", method
            item.reason = reason or self._dict_reason(lengths)
            item.long_positions = self._positions(item, lengths, stem_len)
        return item

    @staticmethod
    def _dict_reason(lengths):
        known = [(c, v) for c, v in lengths if v is not None]
        if len(known) == 1:
            c = known[0][0]
            return f"사전: {c.headword}({c.pos}) [{c.pron}]"
        return f"사전: 동형어 {len(known)}개가 모두 {'장음' if known[0][1] else '단음'}"

    @staticmethod
    def _positions(item, lengths, stem_len):
        """장음 음절의 원문 위치. 용언은 어간이 보이는 범위 안에서만 표시한다."""
        limit = stem_len if stem_len is not None else item.end - item.start
        pron = next((c.pron for c, v in lengths if v and c.pron and "ː" in c.pron), None)
        idx = long_syllables(pron) if pron else [0]  # 발음에 ː가 없으면 축약으로 생긴 장음(보다→봐)
        return [item.start + k for k in idx if k < limit] or [item.start]
