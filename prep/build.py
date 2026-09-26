"""두 사전을 C안으로 합쳐 조회용 SQLite를 만든다.

C안: 기초사전에 있는 표기는 기초사전 항목만 쓰고, 없는 표기만 표준국어대사전 항목을 쓴다.
단어가 아닌 표제어(접사·어미·활용형 안내)는 조회 대상이 아니라서 뺀다.
실행: python -m prep.build
"""
import json
import os
import sqlite3
import time
from pathlib import Path

from . import dicts, rule7

DB_PATH = Path(os.environ.get("JANGDAN_DB", dicts.ROOT / "data" / "jangdan.sqlite"))

# pos: 여럿이면 '/'로 잇는다(조회할 때 나눠서 비교). senses: [[품사, 뜻풀이]]. conj: [[표기, [발음], 활용|준말]]
SCHEMA = """
create table entry(id integer primary key, form text not null, pos text, source text not null,
                   source_id text not null, headword text, homonym_no integer, origin text,
                   pron text, is_long integer, senses text, conj text);
create table example(entry_id integer not null, sense_no integer, kind text, text text not null, citation text);
create table form_class(form text primary key, class text not null);
create table conj_pron(headword text, lemma text, target_code text, pos text, base_pron text,
                       form text, pron text, kind text, is_long integer);
create table rule7_keep(target_code text primary key, lemma text not null, pos text);
create table meta(key text primary key, value text);
"""

# 발음이 있는 항목만 보고 정한다. is_long이 NULL이면 발음이 없는 항목이다.
FORM_CLASS = """
insert into form_class
select form, case when sum(is_long is not null) = 0 then 'nopron'
                  when sum(is_long = 1) = sum(is_long is not null) then 'all_long'
                  when sum(is_long = 1) = 0 then 'all_short'
                  else 'mixed' end
from entry group by form
"""


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v else None


def _write(con, raw_dir, stats):
    kr = list(dicts.read_krdict(raw_dir))
    stats["krdict_bound"] = sum(e.bound for e in kr)
    kr = [e for e in kr if not e.bound]
    kr_forms = {e.form for e in kr}
    entries, examples, next_id, bad = [], [], 1, 0

    def flush():
        con.executemany("insert into entry values (?,?,?,?,?,?,?,?,?,?,?,?)", entries)
        con.executemany("insert into example values (?,?,?,?,?)", examples)
        entries.clear()
        examples.clear()

    def put(e):
        nonlocal next_id, bad
        entries.append((next_id, e.form, e.pos, e.source, e.source_id, e.headword, e.homonym_no, e.origin,
                        "/".join(e.prons) or None, None if e.is_long is None else int(e.is_long),
                        _j(e.senses), _j(e.conj)))
        examples.extend((next_id, *x) for x in e.examples)
        bad += len(e.bad_prons)
        next_id += 1
        if len(entries) >= 5000:
            flush()

    for e in kr:
        put(e)
    stats["krdict_entries"] = len(kr)
    std_kept = std_bound = std_dropped = 0
    for e in dicts.read_stdict(raw_dir):
        if e.bound:
            std_bound += 1
        elif e.form in kr_forms:
            std_dropped += 1
        else:
            put(e)
            std_kept += 1
    flush()
    stats.update(stdict_bound=std_bound, stdict_dropped_by_krdict=std_dropped, stdict_entries=std_kept,
                 bad_prons_dropped=bad)
    if not (stats["krdict_entries"] and std_kept):
        raise RuntimeError(f"항목이 비어 있음: {stats}")

    con.execute(FORM_CLASS)
    rows = rule7.load()
    con.executemany("insert into conj_pron values (?,?,?,?,?,?,?,?,?)",
                    [(r["표제어"], r["lemma"], r["target_code"], r["품사"], r["기본형발음"], r["활용형"],
                      r["활용발음"], r["유형"], int(r["is_long"])) for r in rows])
    con.executemany("insert into rule7_keep values (?,?,?)",
                    [(tc, lemma, pos) for tc, (lemma, pos) in rule7.keep_long(rows).items()])
    con.execute("create index ix_entry_form on entry(form)")
    con.execute("create index ix_example_entry on example(entry_id)")
    for table in ("entry", "example", "form_class", "conj_pron", "rule7_keep"):
        stats[f"rows_{table}"] = con.execute(f"select count(*) from {table}").fetchone()[0]
    stats["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    stats["sources"] = f"{dicts.KRDICT_DIR}, {dicts.STDICT_DIR}"
    con.executemany("insert into meta values (?,?)", [(k, str(v)) for k, v in stats.items()])
    con.commit()
    con.execute("vacuum")


def build(db_path=DB_PATH, raw_dir=dicts.RAW_DIR):
    """임시 파일에 끝까지 만든 뒤에만 기존 DB와 바꾼다."""
    t0 = time.time()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    stats = {}
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA)
        _write(con, raw_dir, stats)
        con.close()
        os.replace(tmp, db_path)  # 대상 DB를 다른 프로세스가 열고 있으면 Windows에서 실패한다
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    stats["size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 1)
    stats["seconds"] = round(time.time() - t0)
    return stats


if __name__ == "__main__":
    for k, v in build().items():
        print(f"{k}: {v}")
