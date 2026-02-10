"""Gemini PDF 파서 — bioRxiv 논문 PDF를 구조화 데이터로 변환

핫이슈 약물(score>=60) 논문만 선택적으로 파싱하여 비용 절감.
동일 PDF 재파싱 방지를 위한 캐싱 지원.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from regscan.config import settings

logger = logging.getLogger(__name__)

# 메모리 캐시 (DOI → 파싱 결과)
_parse_cache: dict[str, dict] = {}

DEFAULT_EXTRACTION_PROMPT = """이 의약품 관련 학술 논문 PDF를 분석하세요.

다음 정보를 JSON 형식으로 추출하세요:

1. drug_names: 논문에서 다루는 약물명 목록
2. indications: 적응증/질환명 목록
3. mechanism_of_action: 작용기전 (MOA) 설명
4. study_type: 연구 유형 (Phase I, II, III, 메타분석, 리뷰 등)
5. key_findings: 핵심 발견 사항 (3-5개)
6. efficacy_data: 유효성 데이터 (주요 엔드포인트 결과)
7. safety_data: 안전성 데이터 (주요 부작용)
8. patient_population: 대상 환자군
9. conclusion: 결론 요약

JSON 형식으로만 응답하세요."""


class GeminiParser:
    """Gemini를 사용한 PDF 내용 추출·구조화

    bioRxiv/medRxiv 프리프린트 PDF에서 약물명, 적응증, MOA, 연구 결과 등을 추출합니다.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self._client = None

    def _get_client(self):
        """Gemini 클라이언트 lazy init"""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(self.model)
            except ImportError:
                raise ImportError(
                    "google-generativeai 패키지가 필요합니다. "
                    "pip install 'regscan[gemini]' 로 설치하세요."
                )
        return self._client

    async def parse_pdf_url(
        self,
        pdf_url: str,
        prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """PDF URL을 파싱하여 구조화 데이터 추출

        Args:
            pdf_url: PDF 파일 URL
            prompt: 커스텀 프롬프트 (None이면 기본 프롬프트 사용)

        Returns:
            {"full_text": ..., "facts": {...}, "cached": bool}
        """
        # 캐시 확인
        cache_key = hashlib.md5(pdf_url.encode()).hexdigest()
        if cache_key in _parse_cache:
            logger.debug("Gemini 캐시 히트: %s", pdf_url)
            result = _parse_cache[cache_key].copy()
            result["cached"] = True
            return result

        if not self.api_key:
            logger.warning("GEMINI_API_KEY 미설정 — PDF 파싱 건너뜀")
            return {"full_text": "", "facts": {}, "cached": False, "error": "no_api_key"}

        prompt = prompt or DEFAULT_EXTRACTION_PROMPT

        try:
            import httpx

            # PDF 다운로드
            async with httpx.AsyncClient(timeout=60.0) as http_client:
                resp = await http_client.get(pdf_url)
                resp.raise_for_status()
                pdf_bytes = resp.content

            # Gemini에 PDF + 프롬프트 전송
            client = self._get_client()
            response = await self._call_gemini(client, pdf_bytes, prompt)

            result = {
                "full_text": response.get("text", ""),
                "facts": response.get("parsed", {}),
                "cached": False,
            }

            # 캐시 저장
            _parse_cache[cache_key] = result
            logger.info("Gemini PDF 파싱 완료: %s", pdf_url)

            return result

        except Exception as e:
            logger.error("Gemini PDF 파싱 실패 (%s): %s", pdf_url, e)
            return {"full_text": "", "facts": {}, "cached": False, "error": str(e)}

    async def _call_gemini(
        self, client, pdf_bytes: bytes, prompt: str
    ) -> dict[str, Any]:
        """Gemini API 호출 (동기 → 비동기 래핑)"""
        import asyncio
        import json

        def _sync_call():
            # Gemini는 PDF 바이트를 직접 처리 가능
            response = client.generate_content(
                [
                    {"mime_type": "application/pdf", "data": pdf_bytes},
                    prompt,
                ]
            )
            text = response.text

            # JSON 추출 시도
            parsed = {}
            try:
                # ```json ... ``` 블록 추출
                if "```json" in text:
                    json_str = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    json_str = text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = text
                parsed = json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                logger.debug("Gemini JSON 파싱 실패 — 원본 텍스트 반환")

            return {"text": text, "parsed": parsed}

        return await asyncio.to_thread(_sync_call)

    def clear_cache(self) -> int:
        """캐시 초기화. 삭제된 항목 수 반환."""
        count = len(_parse_cache)
        _parse_cache.clear()
        return count
