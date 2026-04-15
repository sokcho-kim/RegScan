# 미매칭 성분명 분류 리포트 — Decomposer v1.0.0

> 기준일: 2026-04-15 | MFDS permits_full_20260203.json | 고유 첫-성분 6,414건

## 최종 매칭 결과

| 매칭 방법 | 건수 | 비율 |
|-----------|------|------|
| normalized (기존 정규화) | 4,569 | 71.2% |
| herbal_detected | 937 | 14.6% |
| decomposed_base_fallback | 98 | 1.5% |
| atc | 26 | 0.4% |
| decomposed_variant | 16 | 0.2% |
| **unmatched** | **768** | **12.0%** |

**실질 매칭률**: 88.0% (herbal 포함 시) / 73.3% (herbal 제외 시)

---

## 미매칭 768건 분류

### 카테고리별 분포

| 카테고리 | 고유 성분명 | 품목수 | 비율(품목) | 코드 해결 가능 여부 |
|----------|-----------|--------|-----------|-------------------|
| pure_unmatched | 304 | 1,129 | 41.5% | X — 마스터 미등재 |
| complex_combo | 212 | 531 | 19.5% | X — 부형제/복합 표기 |
| extract | 115 | 295 | 10.8% | X — 추출물/제제 |
| formulation_in_name | 27 | 280 | 10.3% | △ — 일부 제형 분리 가능 |
| gas | 6 | 188 | 6.9% | X — 별도 수가 체계 |
| blood_product | 28 | 182 | 6.7% | X — HIRA 약가 밖 |
| vaccine_bio | 60 | 90 | 3.3% | X — 별도 수가 체계 |
| cell_therapy | 21 | 27 | 1.0% | X — HIRA 약가 밖 |

### 상세 설명

#### 1. pure_unmatched (304건 / 1,129품목)

HIRA 약가 마스터에 해당 성분명 자체가 등재되어 있지 않은 경우.

**대표 항목:**
- `Acetyl-L-Carnitine Hydrochloride` (38품목) — 건강기능식품 경계
- `Rosuvastatin Calcium Micronized` (36품목) — micronized가 분리되나 base "rosuvastatin calcium"이 마스터에 없음
- `Nafamostat Mesylate` (34품목) — 마스터 미등재

**원인**: 마스터 파일(yakga_ingredient_master.csv)의 수록 범위 제한. 연 1회(10월) 갱신 시 자연 해소 가능.

#### 2. complex_combo (212건 / 531품목)

성분명에 부형제(Colloidal Anhydrous Silica 등)가 포함되거나, 슬래시(/) 구분 복합제명.

**대표 항목:**
- `Metformin HCl with Colloidal Anhydrous Silica/Sitagliptin HCl Hydrate` (81품목)
- `Biphenyl Dimethyl Dicarboxylate Mixture/Ursodeoxycholic Acid` (16품목)

**원인**: MFDS 원본에 부형제까지 성분명에 포함. `with` 이후 제거 등 전처리로 일부 구제 가능하나, false positive 위험.

#### 3. extract (115건 / 295품목)

식물/동물 추출물, 제제 형태의 성분명.

**대표 항목:**
- `Titrated Extract of Zea Mays L. Unsaponifiable Fraction` (35품목)
- `Allergen Extract` (33품목)
- `Human Placenta Extract` (24품목)

**원인**: HIRA 약가 체계에서 추출물은 별도 코드 체계. INN 기반 매칭 불가.

#### 4. formulation_in_name (27건 / 280품목)

제형 정보가 성분명의 일부로 들어간 경우.

**대표 항목:**
- `Limaprost Alfadex` (80품목) — alfadex는 cyclodextrin 포접체 → formulation으로 분리 완료
- `Itraconazole Solid Dispersions` (60품목) → formulation으로 분리 완료
- `Duloxetine Hydrochloride Enteric-Coated Granules` (48품목) → enteric-coated 분리 완료

**상태**: FORMULATION_TOKENS 확장으로 대부분 분리 처리됨. 잔여 건은 하이픈 변형 등 edge case.

#### 5. gas (6건 / 188품목)

의료용 가스. HIRA 약가가 아닌 별도 수가로 관리.

- `Oxygen` (103), `Nitrogen` (47), `Carbon Dioxide` (35), `Nitrous Oxide` (2), `Argon` (1)

#### 6. blood_product (28건 / 182품목)

혈액제제. HIRA 약가 체계 밖.

- `Plasma Cryoprecipitates` (31), `Whole Human Blood` (16), `Fresh Frozen Plasma` (16)

#### 7. vaccine_bio (60건 / 90품목)

백신, 항원, 면역글로불린. 별도 수가 체계.

#### 8. cell_therapy (21건 / 27품목)

세포치료제. HIRA 약가 체계 밖.

---

## 결론

미매칭 768건 중 **코드 로직으로 추가 구제 가능한 것은 사실상 없음**.

| 미매칭 원인 | 건수(품목) | 대응 |
|------------|-----------|------|
| 마스터 미등재 | 1,129 | 마스터 갱신(연 1회) 시 자연 해소 |
| 부형제/복합 표기 | 531 | 전처리 가능하나 false positive 위험 > 이득 |
| 추출물/제제 | 295 | INN 체계 밖, 별도 코드 필요 |
| 제형 포함 | 280 | FORMULATION_TOKENS 확장으로 대부분 해결 완료 |
| 가스/혈액/백신/세포 | 487 | HIRA 약가 체계 밖 — 구조적 한계 |

**Decomposer v1.0.0의 책임 범위**: INN 기반 단일 성분의 무손실 분해 및 HIRA 매칭. 위 카테고리는 로직 결함이 아닌 데이터 소스의 구조적 한계이며, 퍼지매칭 도입은 데이터 품질 저하를 초래하므로 불허.
