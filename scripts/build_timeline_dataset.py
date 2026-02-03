"""Timeline ML 학습 데이터셋 구축

MFDS 전체 데이터 수집 → FDA/EMA 매칭 → Timeline 데이터셋 생성
"""

import asyncio
import json
import csv
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.mfds import MFDSPermitIngestor, MFDSClient
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.map.matcher import IngredientMatcher
from regscan.config import settings

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('data/timeline_build.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> Optional[date]:
    """다양한 형식의 날짜 파싱"""
    if not date_str:
        return None

    formats = [
        "%Y-%m-%d",
        "%Y%m%d",
        "%d/%m/%Y",  # EMA 형식
        "%Y.%m.%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_ema_data(ema_file: Path) -> dict[str, dict]:
    """EMA 데이터 로드 및 INN 인덱싱"""
    logger.info(f"EMA 데이터 로드: {ema_file}")

    with open(ema_file, encoding='utf-8') as f:
        ema_raw = json.load(f)

    matcher = IngredientMatcher()
    parser = EMAMedicineParser()

    ema_index = {}
    for item in ema_raw:
        parsed = parser.parse_medicine(item)
        inn = parsed.get('inn', '') or parsed.get('active_substance', '')

        if not inn:
            continue

        normalized = matcher.normalize(inn)
        ma_date = parse_date(parsed.get('marketing_authorisation_date', ''))

        if not ma_date:
            continue

        # 가장 빠른 승인일 유지
        if normalized not in ema_index or ma_date < ema_index[normalized]['approval_date']:
            ema_index[normalized] = {
                'inn': inn,
                'normalized': normalized,
                'approval_date': ma_date,
                'brand_name': parsed.get('name', ''),
                'is_orphan': parsed.get('is_orphan', False),
                'is_prime': parsed.get('is_prime', False),
                'is_conditional': parsed.get('is_conditional', False),
                'is_accelerated': parsed.get('is_accelerated', False),
                'therapeutic_area': parsed.get('therapeutic_area', ''),
                'atc_code': parsed.get('atc_code', ''),
            }

    logger.info(f"EMA 인덱스 생성: {len(ema_index)}개 성분")
    return ema_index


async def collect_mfds_full(output_file: Path, batch_size: int = 100) -> list[dict]:
    """MFDS 전체 데이터 수집"""

    # 이미 수집된 파일이 있으면 사용
    if output_file.exists():
        logger.info(f"기존 MFDS 파일 사용: {output_file}")
        with open(output_file, encoding='utf-8') as f:
            return json.load(f)

    logger.info("MFDS 전체 데이터 수집 시작...")

    all_items = []

    async with MFDSClient() as client:
        # 전체 건수 확인
        total = await client.get_total_count()
        logger.info(f"MFDS 전체 건수: {total:,}")

        # 페이지네이션으로 수집
        page = 1
        while len(all_items) < total:
            try:
                response = await client.search_permits(page_no=page, num_of_rows=batch_size)
                items = response.get('body', {}).get('items', [])

                if not items:
                    break

                all_items.extend(items)

                if len(all_items) % 10000 == 0:
                    logger.info(f"진행: {len(all_items):,}/{total:,} ({100*len(all_items)/total:.1f}%)")

                page += 1
                await asyncio.sleep(0.05)  # Rate limit

            except Exception as e:
                logger.error(f"페이지 {page} 수집 실패: {e}")
                await asyncio.sleep(1)
                continue

    # 저장
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_items, f, ensure_ascii=False, default=str)

    logger.info(f"MFDS 수집 완료: {len(all_items):,}건 → {output_file}")
    return all_items


def build_timeline_dataset(
    mfds_items: list[dict],
    ema_index: dict[str, dict],
    output_csv: Path,
) -> list[dict]:
    """Timeline 데이터셋 구축"""

    logger.info("Timeline 데이터셋 구축 시작...")

    matcher = IngredientMatcher()
    parser = MFDSPermitParser()

    timelines = []
    matched_count = 0

    for item in mfds_items:
        parsed = parser.parse_permit(item)

        # MFDS 영문 성분명 추출
        mfds_inn = parsed.get('main_ingredient', '')
        if not mfds_inn:
            continue

        normalized = matcher.normalize(mfds_inn)

        # EMA 매칭
        ema_data = ema_index.get(normalized)
        if not ema_data:
            continue

        # MFDS 허가일
        mfds_date = parsed.get('permit_date')
        if not mfds_date:
            continue

        if isinstance(mfds_date, datetime):
            mfds_date = mfds_date.date()

        # EMA 승인일
        ema_date = ema_data['approval_date']

        # 소요일 계산
        days_diff = (mfds_date - ema_date).days

        # Timeline 레코드 생성
        timeline = {
            # 식별
            'inn': mfds_inn,
            'normalized_inn': normalized,

            # MFDS 정보
            'mfds_item_seq': parsed.get('item_seq', ''),
            'mfds_item_name': parsed.get('item_name', ''),
            'mfds_company': parsed.get('entp_name', ''),
            'mfds_date': str(mfds_date),
            'mfds_is_new_drug': parsed.get('is_new_drug', False),
            'mfds_is_prescription': parsed.get('is_prescription', False),

            # EMA 정보
            'ema_brand_name': ema_data['brand_name'],
            'ema_date': str(ema_date),
            'ema_is_orphan': ema_data['is_orphan'],
            'ema_is_prime': ema_data['is_prime'],
            'ema_is_conditional': ema_data['is_conditional'],
            'ema_is_accelerated': ema_data['is_accelerated'],
            'ema_therapeutic_area': ema_data['therapeutic_area'],
            'ema_atc_code': ema_data['atc_code'],

            # Target (예측 대상)
            'days_ema_to_mfds': days_diff,
            'mfds_before_ema': days_diff < 0,  # MFDS가 먼저인 경우

            # 피처용
            'atc_level1': ema_data['atc_code'][:1] if ema_data['atc_code'] else '',
            'atc_level2': ema_data['atc_code'][:3] if len(ema_data['atc_code']) >= 3 else '',
            'ema_year': ema_date.year,
            'ema_month': ema_date.month,
        }

        timelines.append(timeline)
        matched_count += 1

    logger.info(f"매칭 완료: {matched_count:,}건")

    # CSV 저장
    if timelines:
        output_csv.parent.mkdir(parents=True, exist_ok=True)

        with open(output_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=timelines[0].keys())
            writer.writeheader()
            writer.writerows(timelines)

        logger.info(f"CSV 저장: {output_csv}")

    # 통계
    if timelines:
        days_list = [t['days_ema_to_mfds'] for t in timelines]
        positive_days = [d for d in days_list if d > 0]
        negative_days = [d for d in days_list if d < 0]

        logger.info("\n=== Timeline 통계 ===")
        logger.info(f"전체 매칭: {len(timelines):,}건")
        logger.info(f"  MFDS 후행 (EMA 먼저): {len(positive_days):,}건")
        logger.info(f"  MFDS 선행 (MFDS 먼저): {len(negative_days):,}건")

        if positive_days:
            logger.info(f"\nMFDS 후행 케이스 통계:")
            logger.info(f"  평균: {sum(positive_days)/len(positive_days):.0f}일 ({sum(positive_days)/len(positive_days)/365:.1f}년)")
            logger.info(f"  최소: {min(positive_days)}일")
            logger.info(f"  최대: {max(positive_days)}일")

    return timelines


async def main():
    if not settings.DATA_GO_KR_API_KEY:
        logger.error("DATA_GO_KR_API_KEY 필요")
        return

    # 파일 경로
    today = datetime.now().strftime("%Y%m%d")
    mfds_file = Path(f"data/mfds/permits_full_{today}.json")
    ema_file = Path("data/ema/medicines_20260203.json")
    output_csv = Path(f"data/ml/timeline_dataset_{today}.csv")

    # EMA 확인
    if not ema_file.exists():
        logger.error(f"EMA 파일 없음: {ema_file}")
        return

    # 1. EMA 로드
    ema_index = load_ema_data(ema_file)

    # 2. MFDS 수집 (전체)
    mfds_items = await collect_mfds_full(mfds_file)

    # 3. Timeline 데이터셋 구축
    timelines = build_timeline_dataset(mfds_items, ema_index, output_csv)

    logger.info("\n" + "=" * 60)
    logger.info(" Timeline 데이터셋 구축 완료!")
    logger.info("=" * 60)
    logger.info(f" 출력 파일: {output_csv}")
    logger.info(f" 레코드 수: {len(timelines):,}건")


if __name__ == "__main__":
    asyncio.run(main())
