"""API: 원고를 받아 장음 표시 결과와 근거를 돌려준다.

실행: uvicorn api.main:create_app --factory
공개 서버에서는 JANGDAN_RATE_PER_MIN(주소당 분당 요청 수)과 JANGDAN_LLM_PER_DAY(하루 LLM 호출 수)로 남용을 막는다.
"""
import ipaddress
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.analyze import Analyzer
from core.judge import Judge
from core.lexicon import Lexicon, LexiconError
from core.llm import from_env
from prep.dicts import ROOT

MAX_CHARS = 2000  # 무료 등급 LLM 한도(분당 토큰)를 넘지 않게 원고 길이를 제한한다
MAX_BODY = 64 * 1024
WEB_DIST = ROOT / "web" / "dist"
PACIFIC = timezone(timedelta(hours=-8))  # Gemini 무료 한도는 태평양 시간 자정에 초기화된다(서머타임에는 한 시간 늦게 센다)
log = logging.getLogger("uvicorn.error")


def env_int(name):
    value = (os.environ.get(name) or "").strip()
    return int(value) if value else 0


def client_ip(request):
    # 끝 값을 접속 주소로 본다. 앞쪽 값은 요청자가 꾸밀 수 있다(Cloud Run에서 꾸민 값을 넣어도 끝 값은 실제 주소였다).
    # IPv6는 한 사용자가 /64 안에서 주소를 바꿀 수 있어 /64 단위로 센다.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    ip = forwarded.rsplit(",", 1)[-1].strip() if forwarded else (request.client.host if request.client else "")
    try:
        if ipaddress.ip_address(ip).version == 6:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    except ValueError:
        pass
    return ip


class RateLimit:
    """주소마다 최근 60초의 요청 수를 센다. 서버 인스턴스가 하나라는 전제의 메모리 카운터다."""

    def __init__(self, per_min):
        self.per_min, self.hits, self.lock = per_min, {}, threading.Lock()

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if len(self.hits) > 10_000:  # 오래된 주소를 비운다. 그래도 많으면 모두 비운다
                self.hits = {k: q for k, q in self.hits.items() if q and q[-1] > now - 60}
                if len(self.hits) > 10_000:
                    self.hits = {}
            q = self.hits.setdefault(key, deque())
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


class DailyLimit:
    """판별기의 실제 호출 수(Judge.calls)를 하루 단위로 센다. 넘으면 LLM 없이 답해 화면에 까닭을 알린다.

    근사치다. 인스턴스가 바뀌면 0부터 다시 세고, 확인을 함께 통과한 요청이나 호출이 여러 번인 원고는 상한을 넘을 수 있다.
    확실한 상한은 결제를 연결하지 않은 Gemini 키의 무료 한도다.
    """

    def __init__(self, judge, per_day):
        self.judge, self.per_day, self.day, self.base, self.lock = judge, per_day, None, 0, threading.Lock()

    def available(self):
        with self.lock:
            day = datetime.now(PACIFIC).date()
            if day != self.day:
                self.day, self.base = day, self.judge.calls
            return self.judge.calls - self.base < self.per_day


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    llm: bool = True  # 끄면 판별 필요 단어를 그대로 둔다


def create_app(analyzer=None, judge=None, rate_per_min=None, llm_per_day=None):
    """분석기와 LLM 판별기는 서버에 하나씩 두고 모든 요청이 함께 쓴다. 한도는 0이면 두지 않는다(로컬 기본)."""
    analyzer = analyzer or Analyzer(Lexicon.from_env())
    analyzer.kiwi.tokenize("서버를 켤 때 형태소 분석기를 데운다.")  # 첫 분석에 드는 모델 적재 시간(약 2초)을 미리 쓴다
    if judge is None and (backend := from_env()) is not None:
        judge = Judge(backend)
    rate_per_min = env_int("JANGDAN_RATE_PER_MIN") if rate_per_min is None else rate_per_min
    llm_per_day = env_int("JANGDAN_LLM_PER_DAY") if llm_per_day is None else llm_per_day
    rate = RateLimit(rate_per_min) if rate_per_min > 0 else None
    daily = DailyLimit(judge, llm_per_day) if judge is not None and llm_per_day > 0 else None
    kiwi_lock = threading.Lock()  # Kiwi의 스레드 안전성은 확인하지 않아 분석은 한 번에 하나씩 한다
    app = FastAPI(title="한국어 장단음 분석기")

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        size = request.headers.get("content-length")
        if request.method == "POST" and size is None:  # chunked 본문은 크기를 미리 알 수 없어 받지 않는다
            return JSONResponse({"detail": "Content-Length가 필요합니다"}, status_code=411)
        if size is not None and (not size.isdigit() or int(size) > MAX_BODY):
            return JSONResponse({"detail": f"요청이 너무 큽니다({MAX_BODY // 1024}KB까지)"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        # 기본 처리기는 입력을 그대로 되돌려 준다(짝 없는 서로게이트면 500, 큰 원고면 큰 응답). 입력은 빼고 알린다.
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
                            status_code=422)

    @app.post("/api/analyze")
    def analyze(req: AnalyzeRequest, request: Request):
        start = time.perf_counter()
        if rate is not None and not rate.allow(client_ip(request)):
            return JSONResponse({"detail": "요청이 너무 많습니다"}, status_code=429)
        try:
            with kiwi_lock:
                result = analyzer.analyze(req.text)
        except LexiconError as e:
            log.exception("사전 DB 조회 실패")  # 원인(__cause__)은 서버 로그에만 남긴다
            return JSONResponse({"detail": str(e)}, status_code=503)
        use_llm = req.llm and judge is not None
        limited = use_llm and daily is not None and not daily.available()  # 한도를 다 쓰면 사전·규칙 결과만 돌려준다
        use_llm = use_llm and not limited
        if use_llm:
            judge.resolve(result)
        out = result.to_dict()
        for it in out["items"]:  # 후보 목록은 판별 필요·LLM 단어에만 둔다(응답 크기)
            if it["status"] != "undecided" and it["method"] != "llm":
                it["candidates"] = []
        out["meta"] = {"db": analyzer.lex.source, "llm": judge.backend.model if use_llm else None,
                       "llm_limited": limited, "elapsed_ms": round((time.perf_counter() - start) * 1000)}
        return out

    if WEB_DIST.exists():  # 화면(빌드 결과)을 같은 주소에서 내보낸다
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
