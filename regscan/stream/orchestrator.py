"""Stream Orchestrator — 3개 스트림 실행 + 결과 병합

StreamOrchestrator.run_all()이 pipeline.py의 Step 2를 대체.
"""

from __future__ import annotations

import logging
from typing import Any

from regscan.config import settings
from regscan.map.matcher import IngredientMatcher
from .base import BaseStream, StreamResult

logger = logging.getLogger(__name__)


class StreamOrchestrator:
    """3-Stream 실행 오케스트레이터"""

    def __init__(
        self,
        enabled_streams: list[str] | None = None,
        areas: list[str] | None = None,
    ):
        """
        Args:
            enabled_streams: 실행할 스트림 목록 (None이면 settings에서 읽음)
            areas: 치료영역 필터 (therapeutic 스트림 전용)
        """
        self._streams: list[BaseStream] = []
        self._matcher = IngredientMatcher()

        if enabled_streams is None:
            enabled_streams = []
            if settings.ENABLE_STREAM_THERAPEUTIC:
                enabled_streams.append("therapeutic")
            if settings.ENABLE_STREAM_INNOVATION:
                enabled_streams.append("innovation")
            if settings.ENABLE_STREAM_EXTERNAL:
                enabled_streams.append("external")

        for name in enabled_streams:
            stream = self._create_stream(name, areas=areas)
            if stream:
                self._streams.append(stream)

    def _create_stream(
        self, name: str, areas: list[str] | None = None,
    ) -> BaseStream | None:
        """스트림 이름으로 인스턴스 생성"""
        if name == "therapeutic":
            from .therapeutic import TherapeuticAreaStream
            return TherapeuticAreaStream(areas=areas)
        elif name == "innovation":
            from .innovation import InnovationStream
            return InnovationStream()
        elif name == "external":
            from .external import ExternalSignalStream
            return ExternalSignalStream()
        else:
            logger.warning("알 수 없는 스트림: %s", name)
            return None

    async def run_all(self) -> dict[str, list[StreamResult]]:
        """모든 활성 스트림 실행

        Returns:
            {stream_name: [StreamResult, ...]}
        """
        all_results: dict[str, list[StreamResult]] = {}

        for stream in self._streams:
            logger.info("=== 스트림 실행: %s ===", stream.stream_name)
            try:
                results = await stream.collect()
                all_results[stream.stream_name] = results

                total_drugs = sum(r.drug_count for r in results)
                total_signals = sum(r.signal_count for r in results)
                logger.info(
                    "  스트림 '%s' 완료: %d개 결과, 총 %d개 약물, %d개 시그널",
                    stream.stream_name, len(results), total_drugs, total_signals,
                )
            except Exception as e:
                logger.error("스트림 '%s' 실행 실패: %s", stream.stream_name, e)
                all_results[stream.stream_name] = [
                    StreamResult(
                        stream_name=stream.stream_name,
                        errors=[str(e)],
                    )
                ]

        return all_results

    def merge_results(
        self,
        stream_results: dict[str, list[StreamResult]],
    ) -> list[dict[str, Any]]:
        """모든 스트림 결과를 INN 기준으로 병합 + 중복 제거

        Returns:
            [{inn, normalized_name, therapeutic_areas, stream_sources,
              fda_data, ema_data, atc_code, ...}]
        """
        merged: dict[str, dict[str, Any]] = {}  # normalized_inn -> merged drug

        for stream_name, results in stream_results.items():
            for result in results:
                for drug in result.drugs_found:
                    inn = drug.get("inn", "")
                    if not inn:
                        continue
                    norm = self._matcher.normalize(inn)

                    if norm in merged:
                        existing = merged[norm]
                        # 스트림 소스 추가
                        if stream_name not in existing["stream_sources"]:
                            existing["stream_sources"].append(stream_name)
                        # 치료영역 추가
                        for ta in drug.get("therapeutic_areas", []):
                            if ta not in existing["therapeutic_areas"]:
                                existing["therapeutic_areas"].append(ta)
                        # FDA/EMA 데이터 병합
                        if drug.get("fda_data") and not existing.get("fda_data"):
                            existing["fda_data"] = drug["fda_data"]
                        if drug.get("ema_data") and not existing.get("ema_data"):
                            existing["ema_data"] = drug["ema_data"]
                        # ATC 코드 병합
                        if drug.get("atc_code") and not existing.get("atc_code"):
                            existing["atc_code"] = drug["atc_code"]
                        # 시그널 병합
                        for sig in drug.get("signals", []):
                            existing.setdefault("signals", []).append(sig)
                    else:
                        merged[norm] = {
                            "inn": inn,
                            "normalized_name": norm,
                            "therapeutic_areas": list(drug.get("therapeutic_areas", [])),
                            "stream_sources": [stream_name],
                            "fda_data": drug.get("fda_data"),
                            "ema_data": drug.get("ema_data"),
                            "atc_code": drug.get("atc_code", ""),
                            "signals": list(drug.get("signals", [])),
                        }

        return list(merged.values())

    def build_global_statuses(self, merged: list[dict]) -> list:
        """병합된 약물 목록 → GlobalRegulatoryStatus 목록

        기존 GlobalStatusBuilder 재사용.
        """
        from regscan.map.global_status import GlobalStatusBuilder

        builder = GlobalStatusBuilder()
        statuses = []

        for drug in merged:
            fda_data = drug.get("fda_data")
            ema_data = drug.get("ema_data")
            status = builder.build_from_fda_ema(fda_data, ema_data)

            # 스트림 메타 주입
            status._therapeutic_areas = drug.get("therapeutic_areas", [])
            status._stream_sources = drug.get("stream_sources", [])

            statuses.append(status)

        return statuses
