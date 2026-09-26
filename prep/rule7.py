"""표준국어대사전 활용 발음으로 제7항 예외(모음 어미 앞에서도 장음 유지) 목록을 만든다.

stdict_conj_pron.csv: 국립국어원 표준국어대사전 웹 페이지의 활용 발음(단음절 장음 용언 276항목, 2026-09-25 수집),
CC BY-SA 2.0 KR. 「유형」 열은 표면형으로 대략 나눈 값이라 모음 어미 장음 행은 review()로 다시 확인한다.
실행: python -m prep.rule7 [검토표.md]
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from jamo import h2j, j2hcj

CSV_PATH = Path(__file__).with_name("stdict_conj_pron.csv")


def load(path=CSV_PATH):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["lemma"] = re.sub(r"\d+$", "", r["표제어"])
        r["is_long"] = r["장음"] == "True"
    return rows


def initial(syllable):
    """한글 음절의 초성(호환 자모). 한글이 아니면 그대로 돌려준다."""
    return j2hcj(h2j(syllable))[0]


def review(rows):
    """모음 어미형 장음 행: 어간 다음 음절의 초성이 ㅇ인지, 장음이 첫음절에 있는지 본다.

    초성 ㅇ 검사는 수집 때의 분류 기준과 같아서 독립 검사가 아니다(단음절 어간 뒤 음절의 초성이 ㅇ이면
    모음으로 시작하는 어미다). 독립 검사는 첫음절 장음(first_long)뿐이다.
    """
    out = []
    for r in rows:
        if r["유형"] != "모음어미" or not r["is_long"]:
            continue
        nxt = r["활용형"][1:2]
        out.append({**r, "next": nxt, "vowel_ending": bool(nxt) and initial(nxt) == "ㅇ",
                    "first_long": all(p.find("ː") == 1 for p in r["활용발음"].split("/"))})
    return out


def inconsistent(rows):
    """같은 항목의 모음 어미형 가운데 장음과 단음이 섞인 target_code."""
    by = defaultdict(set)
    for r in rows:
        if r["유형"] == "모음어미":
            by[r["target_code"]].add(r["is_long"])
    return sorted(tc for tc, v in by.items() if len(v) > 1)


def keep_long(rows):
    """모음 어미 앞에서도 장음을 유지하는 항목: {target_code: (원형, 품사)}"""
    return {r["target_code"]: (r["lemma"], r["품사"]) for r in rows if r["유형"] == "모음어미" and r["is_long"]}


def key_conflicts(rows):
    """(원형, 품사)가 같은데 장음 유지 여부가 다른 동형어. 비어 있어야 (원형, 품사)로 바로 찾을 수 있다."""
    keep = keep_long(rows)
    by = defaultdict(set)
    for r in rows:
        if r["유형"] == "모음어미":
            by[(r["lemma"], r["품사"])].add(r["target_code"] in keep)
    return sorted(k for k, v in by.items() if len(v) > 1)


def report(rows):
    rev = review(rows)
    keep = keep_long(rows)
    listed = {"끌다", "떫다", "벌다", "썰다", "없다"}  # 표준발음법 제7항 다만에 예시된 어간
    lines = ["# 제7항 예외 검토 (표준국어대사전 활용 발음)", "",
             f"- 전체 {len(rows)}행, 모음 어미 장음 {len(rev)}행."
             + (" 이 41행은 2026-09-26에 하나씩 확인했고 모두 실제 모음 어미형이다." if len(rev) == 41 else
                " 확인해 둔 41행과 수가 달라 다시 확인해야 한다."),
             f"- 어간 다음 음절 초성이 ㅇ(모음 어미): {sum(r['vowel_ending'] for r in rev)}/{len(rev)}. "
             "수집 때의 분류 기준과 같은 조건이라 독립 검사는 아니다.",
             f"- 장음이 첫음절에 있음: {sum(r['first_long'] for r in rev)}/{len(rev)}",
             f"- 같은 항목 안에서 모음 어미형 장단이 섞인 항목: {inconsistent(rows) or '없음'}",
             f"- (원형, 품사) 키 충돌: {key_conflicts(rows) or '없음'}",
             f"- 장음 유지 항목 {len(keep)}개, 원형 {len({v[0] for v in keep.values()})}개, "
             f"(원형, 품사) 키 {len(set(keep.values()))}개",
             f"- 규정 예시에 없는 원형: {', '.join(sorted({v[0] for v in keep.values()} - listed))}",
             f"- 「기타」 행: {[(r['표제어'], r['활용형'], r['활용발음']) for r in rows if r['유형'] == '기타']}",
             "", "| 표제어 | 품사 | 활용형 | 활용 발음 | 어간 다음 음절 | 모음 어미 | 첫음절 장음 |",
             "|---|---|---|---|---|---|---|"]
    for r in rev:
        lines.append(f"| {r['표제어']} | {r['품사']} | {r['활용형']} | [{r['활용발음']}] | {r['next']} | "
                     f"{'O' if r['vowel_ending'] else 'X'} | {'O' if r['first_long'] else 'X'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = report(load())
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    print(text)
