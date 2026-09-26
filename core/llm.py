"""LLM 공급자. 임시로 Gemini 무료 등급을 쓴다. 공급자는 (system, prompt, schema) → JSON 문자열만 맞추면 바꿀 수 있다."""
import os

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from prep.dicts import ROOT

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # 무료 등급 하루 한도: 3.8-flash 20회, 3.5-flash-lite 500회


class LLMError(Exception):
    """호출 실패나 빈 응답. 해당 단어는 판별 필요로 남긴다.

    stop: 한도 초과·서버 오류·연결 실패처럼 다음 요청도 실패할 오류. 이때는 남은 요청을 보내지 않는다.
    """

    def __init__(self, message, stop=False):
        super().__init__(message)
        self.stop = stop


class Gemini:
    """Gemini 3는 temperature를 기본값(1.0)으로 두라고 권한다. 모델, thinking 수준, seed만 고정하고 재현은 캐시로 한다."""

    # thinking: 3.5-flash-lite는 LOW에서 출력이 깨졌다(따옴표가 붙은 엉뚱한 글자, 오타). MINIMAL은 깨끗하고 빠르다.
    def __init__(self, model=DEFAULT_MODEL, thinking="MINIMAL", seed=0, timeout_ms=30_000, api_key=None, http_client=None):
        self.model = model
        self.id = f"gemini/{model}/thinking={thinking}/seed={seed}"
        self.last_usage = None  # 마지막 호출의 토큰 수(평가용)
        # 재시도하지 않는다(retry_options 없음). 429는 기다려도 풀리지 않을 수 있고, 시간 초과를 다시 보내면 한도를 또 쓴다.
        self._client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"), vertexai=False,
                                    http_options=types.HttpOptions(timeout=timeout_ms, httpx_client=http_client))
        self._config = dict(thinking_config=types.ThinkingConfig(thinking_level=thinking), seed=seed,
                            response_mime_type="application/json",
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))

    def __call__(self, system, prompt, schema):
        config = types.GenerateContentConfig(system_instruction=system, response_json_schema=schema, **self._config)
        try:
            r = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except errors.APIError as e:  # 요청 내용 탓(400)이면 다음 요청은 보낸다. 키·모델 이름 오류는 멈춘다
            stop = e.code in (401, 403, 404, 429) or e.code >= 500 or "api key" in str(e).lower()
            raise LLMError(f"API 오류 {e.code}", stop=stop) from e
        except (httpx.HTTPError, ValueError) as e:  # 연결 실패·시간 초과, JSON이 아닌 응답 본문
            raise LLMError(type(e).__name__, stop=True) from e
        self.last_usage = r.usage_metadata
        if not r.text:
            blocked = r.prompt_feedback.block_reason if r.prompt_feedback else None
            finish = r.candidates[0].finish_reason if r.candidates else None
            raise LLMError(f"빈 응답 {blocked or finish}")
        return r.text


def from_env():
    """.env의 키로 공급자를 만든다. 키가 없으면 None이고, 판별 필요 단어는 그대로 남는다."""
    load_dotenv(ROOT / ".env")
    if os.environ.get("GEMINI_API_KEY"):
        return Gemini(os.environ.get("JANGDAN_LLM_MODEL") or DEFAULT_MODEL,
                      os.environ.get("JANGDAN_LLM_THINKING") or "MINIMAL")
    return None
