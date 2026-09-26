"""로컬 API: 원고를 받아 장음 표시 결과와 근거를 돌려준다.

실행: uvicorn api.main:create_app --factory
"""
import logging
import threading
import time

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
log = logging.getLogger("uvicorn.error")


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    llm: bool = True  # 끄면 판별 필요 단어를 그대로 둔다


def create_app(analyzer=None, judge=None):
    """분석기와 LLM 판별기는 서버에 하나씩 두고 모든 요청이 함께 쓴다."""
    analyzer = analyzer or Analyzer(Lexicon.from_env())
    analyzer.kiwi.tokenize("서버를 켤 때 형태소 분석기를 데운다.")  # 첫 분석에 드는 모델 적재 시간(약 2초)을 미리 쓴다
    if judge is None and (backend := from_env()) is not None:
        judge = Judge(backend)
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
    def analyze(req: AnalyzeRequest):
        start = time.perf_counter()
        try:
            with kiwi_lock:
                result = analyzer.analyze(req.text)
        except LexiconError as e:
            log.exception("사전 DB 조회 실패")  # 원인(__cause__)은 서버 로그에만 남긴다
            return JSONResponse({"detail": str(e)}, status_code=503)
        use_llm = req.llm and judge is not None
        if use_llm:
            judge.resolve(result)
        out = result.to_dict()
        for it in out["items"]:  # 후보 목록은 판별 필요·LLM 단어에만 둔다(응답 크기)
            if it["status"] != "undecided" and it["method"] != "llm":
                it["candidates"] = []
        out["meta"] = {"db": analyzer.lex.source, "llm": judge.backend.model if use_llm else None,
                       "elapsed_ms": round((time.perf_counter() - start) * 1000)}
        return out

    if WEB_DIST.exists():  # 6단계 화면(빌드 결과)을 같은 주소에서 내보낸다
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
