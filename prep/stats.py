"""기획안 부록 A.1 통계를 다시 계산하고 병합 DB를 요약한다.

실행: python -m prep.stats [출력 폴더]  (폴더를 주면 두 표를 md 파일로도 쓴다)
"""
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import dicts
from .build import DB_PATH

# 기획안 부록 A.1과 기획자료/사전대조/대조결과_20260925.txt의 값
A1 = {
    "기초 단어 표기 수": 47006, "표준 단어 표기 수": 288618,
    "기초 혼재 표기": 679, "표준 혼재 표기": 11498,
    "기초 혼재 표기의 평균 동형어 수": 2.6, "표준 혼재 표기의 평균 동형어 수": 4.0,
    "표준 혼재 중 기초에도 있는 표기": 4698,
    "  그중 기초에서 전부 단음": 2080, "  그중 기초에서 전부 장음": 1917,
    "  그중 기초에서 혼재": 677, "  그중 기초에서 발음 없음": 24,
}


def classify(flags):
    known = [f for f in flags if f is not None]
    if not known:
        return "nopron"
    return "all_long" if all(known) else ("all_short" if not any(known) else "mixed")


def _groups(entries, key):
    g = defaultdict(list)
    for e in entries:
        g[key(e)].append(e.is_long)
    return g


def reproduce(raw_dir=dicts.RAW_DIR):
    """계획 단계와 같은 규칙으로 센다: 기초는 붙임표를 두고, 표준은 붙임표를 모두 지우며, 발음 값은 검증하지 않는다."""
    K = _groups(dicts.read_krdict(raw_dir, strict=False), lambda e: e.form)
    S = _groups(dicts.read_stdict(raw_dir, strict=False), lambda e: e.form.replace("-", ""))
    kc = {f: classify(v) for f, v in K.items()}
    sc = {f: classify(v) for f, v in S.items()}
    km = [f for f in K if kc[f] == "mixed"]
    sm = [f for f in S if sc[f] == "mixed"]
    both = Counter(kc[f] for f in sm if f in K)
    return {
        "기초 단어 표기 수": len(K), "표준 단어 표기 수": len(S),
        "기초 혼재 표기": len(km), "표준 혼재 표기": len(sm),
        "기초 혼재 표기의 평균 동형어 수": round(statistics.mean(len(K[f]) for f in km), 1),
        "표준 혼재 표기의 평균 동형어 수": round(statistics.mean(len(S[f]) for f in sm), 1),
        "표준 혼재 중 기초에도 있는 표기": sum(both.values()),
        "  그중 기초에서 전부 단음": both["all_short"], "  그중 기초에서 전부 장음": both["all_long"],
        "  그중 기초에서 혼재": both["mixed"], "  그중 기초에서 발음 없음": both["nopron"],
    }


def a1_table(got):
    lines = ["# 부록 A.1 통계 재현", "", "계획 단계와 같은 표기 규칙으로 두 사전을 따로 셌다. 짝짓기 통계(번호 일치율, 장음 불일치 88쌍)는 D안 범위라 제외했다.",
             "", "| 항목 | A.1 | 재계산 | 일치 |", "|---|---|---|---|"]
    for k, v in A1.items():
        lines.append(f"| {k.strip()} | {v:,} | {got[k]:,} | {'O' if got[k] == v else 'X'} |")
    return "\n".join(lines) + "\n"


def open_db(db_path=DB_PATH):
    """읽기 전용으로 연다. 없는 경로에 빈 DB 파일을 만들지 않는다."""
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB 없음: {db_path} (python -m prep.build 먼저)")
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def db_summary(db_path=DB_PATH):
    con = open_db(db_path)
    q = lambda sql: con.execute(sql).fetchall()
    meta = dict(q("select key, value from meta"))
    lines = ["# 병합 DB 통계 (C안)", "",
             f"- 빌드 시각 {meta['built_at']}, 파일 크기 {Path(db_path).stat().st_size / 1024 / 1024:.1f}MB",
             f"- 원본: {meta['sources']}",
             f"- 항목: 기초사전 {int(meta['krdict_entries']):,}개, 표준국어대사전 {int(meta['stdict_entries']):,}개",
             f"- 뺀 항목: 단어가 아닌 표제어(접사·어미·활용형 안내) 기초 {int(meta['krdict_bound']):,}개·"
             f"표준 {int(meta['stdict_bound']):,}개, 기초사전에 있는 표기라 뺀 표준 항목 "
             f"{int(meta['stdict_dropped_by_krdict']):,}개",
             f"- 현대 한글 발음이 아니라서 버린 값 {int(meta['bad_prons_dropped'])}개",
             f"- 표기 {int(meta['rows_form_class']):,}개의 3분류: "
             + ", ".join(f"{c} {n:,}" for c, n in q("select class, count(*) from form_class group by class order by 2 desc")),
             "- 예문: " + ", ".join(f"{s} {n:,}개" for s, n in q(
                 "select e.source, count(*) from example x join entry e on e.id = x.entry_id group by e.source"))
             + f" (출전이 있는 표준 용례 {q('select count(*) from example where citation is not null')[0][0]:,}개)",
             f"- 제7항: 활용 발음 {int(meta['rows_conj_pron'])}행, 모음 어미 앞 장음 유지 {int(meta['rows_rule7_keep'])}항목"]
    con.close()
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    db = db_summary()
    a1 = a1_table(reproduce())
    print(a1)
    print(db)
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "2단계_A1_통계_재현.md").write_text(a1, encoding="utf-8")
        (out / "2단계_병합DB_통계.md").write_text(db, encoding="utf-8")
