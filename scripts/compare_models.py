"""LLM 모델 비교 테스트

gpt-4o-mini vs gpt-4o 브리핑 품질 비교
"""

import sys
import io
import asyncio
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.api.deps import get_data_store
from regscan.report.llm_generator import LLMBriefingGenerator


async def compare_single_drug(inn: str, models: list[tuple[str, str]]):
    """단일 약물에 대해 여러 모델 비교"""
    store = get_data_store()
    impact = store.get_by_inn(inn)

    if not impact:
        print(f"약물 '{inn}'을 찾을 수 없습니다.")
        return

    print(f"\n{'='*70}")
    print(f"약물: {impact.inn}")
    print(f"상태: {impact.domestic_status.value}")
    print(f"HIRA: {impact.hira_status.value if impact.hira_status else 'N/A'}")
    print(f"가격: ₩{impact.hira_price:,.0f}" if impact.hira_price else "가격: N/A")
    print(f"{'='*70}")

    results = {}

    for provider, model in models:
        print(f"\n--- {provider}/{model} ---")
        start_time = time.time()

        try:
            generator = LLMBriefingGenerator(provider=provider, model=model)
            report = await generator.generate(impact)
            elapsed = time.time() - start_time

            results[f"{provider}/{model}"] = {
                "report": report,
                "time": elapsed,
            }

            print(f"시간: {elapsed:.2f}초")
            print(f"\nHeadline: {report.headline}")
            print(f"Subtitle: {report.subtitle}")
            print(f"\nKey Points:")
            for i, point in enumerate(report.key_points, 1):
                print(f"  {i}. {point[:80]}{'...' if len(point) > 80 else ''}")
            print(f"\nMedclaim: {report.medclaim_section[:150]}...")

        except Exception as e:
            print(f"오류: {e}")
            results[f"{provider}/{model}"] = {"error": str(e)}

    return results


async def main():
    """메인 비교 실행"""
    print("=" * 70)
    print("LLM 모델 비교 테스트")
    print("=" * 70)

    # 비교할 모델들
    models = [
        ("openai", "gpt-4o-mini"),
        ("openai", "gpt-4o"),
    ]

    # 테스트 약물들
    test_drugs = [
        "pembrolizumab",  # 급여 고가 항암제
        "ELRANATAMAB",    # 국내 미허가 + 임상 진행
    ]

    for inn in test_drugs:
        await compare_single_drug(inn, models)

    print("\n" + "=" * 70)
    print("비교 테스트 완료!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
