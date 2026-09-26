"""한국어기초사전·표준국어대사전 전체 내려받기 XML을 단어 항목으로 읽는다."""
import glob
import io
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.environ.get("JANGDAN_RAW_DIR", ROOT.parent / "원시데이터(사전, 말뭉치 등)"))
KRDICT_DIR = "전체 내려받기_한국어기초사전_xml_20260919"
STDICT_DIR = "전체 내려받기_표준국어대사전_xml_20260905"

# XML에 허용되지 않는 제어문자. 기초사전 일부 파일에 \x08이 있어 파서가 멈춘다.
_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HOMONYM = re.compile(r"^(.*?)(\d{2})?$")
_PRON_OK = re.compile(r"^[가-힣ㄱ-ㅣ][가-힣ㄱ-ㅣː]*$")  # 현대 한글로 시작하고 ː는 음절 뒤에만
_NOT_WORD_POS = {"어미", "접사"}


@dataclass
class Entry:
    source: str       # krdict | stdict
    source_id: str    # 기초사전 LexicalEntry id | 표준국어대사전 target_code
    headword: str     # 사전 표기 그대로
    form: str         # 조회용 표기
    bound: bool       # 단어가 아닌 표제어: 앞뒤 붙임표(접사·어미·활용형 안내) 또는 품사가 어미·접사
    homonym_no: int
    pos: str          # 품사, 여럿이면 '/'로 잇는다
    origin: str       # 원어. 표준은 한자만, 이표기는 '/'로 구분
    prons: list       # 정규화한 발음
    conj: list        # [(표기, [발음...], 활용|준말)]
    senses: list      # [(품사, 뜻풀이)]
    examples: list    # [(뜻풀이 번호, 유형, 문장, 출전)]
    bad_prons: list = field(default_factory=list)  # 현대 한글 발음이 아니라서 버린 값

    @property
    def is_long(self):
        return any("ː" in p for p in self.prons) if self.prons else None


def norm_pron(p):
    if p is None:
        return None
    p = re.sub("ː+", "ː", p.strip().replace(":", "ː"))
    return p or None


def _prons(values, strict, bad=None):
    """strict이면 한 칸에 '/'로 이어 적은 이형을 나누고, 한글과 ː로만 된 값만 남긴다(일부 발음 칸에 한자가 있음)."""
    out = []
    for p in map(norm_pron, values):
        if not p:
            continue
        if not strict:
            out.append(p)
            continue
        for part in (x.strip() for x in p.split("/")):
            if _PRON_OK.match(part):
                out.append(part)
            elif part and bad is not None:
                bad.append(part)
    return out


def _xml(path):
    with open(path, encoding="utf-8") as fh:
        return io.BytesIO(_CTRL.sub("", fh.read()).encode("utf-8"))


def _files(raw_dir, sub):
    files = sorted(glob.glob(str(Path(raw_dir) / sub / "*.xml")))
    if not files:
        raise FileNotFoundError(f"사전 XML이 없음: {Path(raw_dir) / sub}")
    return files


def _is_bound(form, pos):
    return form.startswith("-") or form.endswith("-") or bool(_NOT_WORD_POS & set(pos.split("/")))


def _val(el, att):
    f = el.find(f'feat[@att="{att}"]')
    return (f.get("val") or "").strip() if f is not None else ""


def read_krdict(raw_dir=RAW_DIR, strict=True):
    """기초사전의 단어 단위 항목. 표기는 공백만 지운다."""
    for path in _files(raw_dir, KRDICT_DIR):
        for _, el in ET.iterparse(_xml(path)):
            if el.tag != "LexicalEntry":
                continue
            feats = {f.get("att"): f.get("val") for f in el.findall("feat")}
            if feats.get("lexicalUnit") != "단어":
                el.clear()
                continue
            lemma = el.find('Lemma/feat[@att="writtenForm"]')
            head = (lemma.get("val") if lemma is not None else "").strip()
            pos = feats.get("partOfSpeech") or ""
            prons, conj, bad = [], [], []
            for wf in el.findall("WordForm"):
                kind = _val(wf, "type")
                ps = _prons((f.get("val") for f in wf.findall('feat[@att="pronunciation"]')), strict, bad)
                if kind == "발음":
                    prons += ps
                    continue
                if _val(wf, "writtenForm"):
                    conj.append((_val(wf, "writtenForm"), ps, kind))
                for rep in wf.findall("FormRepresentation"):  # 준말 활용형(해, 봐 등)
                    if _val(rep, "writtenForm"):
                        conj.append((_val(rep, "writtenForm"),
                                     _prons((f.get("val") for f in rep.findall('feat[@att="pronunciation"]')), strict, bad),
                                     _val(rep, "type")))
            senses, examples = [], []
            for no, s in enumerate(el.findall("Sense"), 1):  # 웹과 같은 XML 순서
                senses.append((pos, _val(s, "definition")))
                for ex in s.findall("SenseExample"):
                    lines = [v for v in ((f.get("val") or "").strip() for f in ex.findall('feat[@att="example"]')) if v]
                    if lines:
                        examples.append((no, _val(ex, "type") or None, "\n".join(lines), None))
            form = head.replace(" ", "")
            yield Entry("krdict", el.get("val"), head, form, _is_bound(form, pos),
                        int(feats.get("homonym_number") or 0), pos, feats.get("origin") or "",
                        prons, conj, senses, examples, bad)
            el.clear()


def read_stdict(raw_dir=RAW_DIR, strict=True):
    """표준국어대사전의 단어 단위 항목. 표기는 번호·^·공백·가운데 붙임표를 지우고, 앞뒤 붙임표는 남긴다."""
    for path in _files(raw_dir, STDICT_DIR):
        for _, el in ET.iterparse(_xml(path)):
            if el.tag != "item":
                continue
            wi = el.find("word_info")
            if wi is None or wi.findtext("word_unit") != "단어":
                el.clear()
                continue
            raw = wi.findtext("word") or ""
            m = _HOMONYM.match(raw)
            base = m.group(1)
            core = base.strip("-").replace("-", "").replace("^", "").replace(" ", "")
            form = ("-" if base.startswith("-") else "") + core + ("-" if base.endswith("-") else "")
            pos_list = [pi.findtext("pos") or "" for pi in wi.findall("pos_info")]
            pos = "/".join(pos_list)
            bad = []
            conj = []
            for ci in wi.findall("conju_info"):
                for tag, text, kind in (("conjugation_info", "conjugation", "활용"), ("abbreviation_info", "abbreviation", "준말")):
                    for c in ci.iter(tag):
                        if (c.findtext(text) or "").strip():
                            conj.append((c.findtext(text).strip(),
                                         _prons((p.text for p in c.iter("pronunciation")), strict, bad), kind))
            # 한자 원어와 이표기 구분자('/(병기)')만 잇는다. 합성어의 부분은 붙고, 이표기는 '/'로 갈린다.
            # 이표기가 모두 한자가 아니면(D/d 등) 구분자만 남으므로 걷어 낸다.
            origin = "".join(o.findtext("original_language") or "" for o in wi.findall("original_language_info")
                             if (o.findtext("language_type") or "") == "한자"
                             or (o.findtext("language_type") or "").startswith("/"))
            origin = re.sub("/+", "/", origin).strip("/")
            pos_of = {id(s): pi.findtext("pos") or "" for pi in wi.findall("pos_info") for s in pi.iter("sense_info")}
            senses, examples = [], []
            for no, s in enumerate(wi.iter("sense_info"), 1):
                senses.append((pos_of.get(id(s), ""), (s.findtext("definition") or "").strip()))
                for ex in s.findall("example_info"):
                    text = (ex.findtext("example") or "").strip()
                    if text:
                        examples.append((no, None, text, (ex.findtext("source") or "").strip() or None))
            prons = _prons((x.text for x in wi.findall("pronunciation_info/pronunciation")), strict, bad)
            yield Entry("stdict", el.findtext("target_code"), raw, form, _is_bound(form, pos),
                        int(m.group(2) or 0), pos, origin, prons, conj, senses, examples, bad)
            el.clear()
