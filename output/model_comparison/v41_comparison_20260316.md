# V4.1 모델 비교 — POLATUZUMAB VEDOTIN (2026-03-16)

## 테스트 조건
- **약물**: Polatuzumab Vedotin (CD79b ADC, DLBCL)
- **프롬프트**: V4.1 Executive Tone (BLUF + So What + 간결문장 + 액션 아이템)
- **팩트 데이터**: 동일 DomesticImpact 객체 (global_score=70, korea_relevance=25, quadrant=watch)

| 항목 | GPT-5.2 | Gemini 2.5 Flash | Gemini 3 Flash Preview |
|------|---------|-------------------|------------------------|
| 응답시간 | 19.7s | 17.9s | 19.7s |
| BLUF | ✅ 완벽 | ✅ 양호 | ✅ 양호 |
| So What | ✅ "그래서~" 일관 | △ 부분 적용 | △ 부분 적용 |
| 간결성 (40자) | ✅ 최고 | △ 길어지는 경향 | ○ 중간 |
| 액션 아이템 | ✅ 가장 구체적 | ○ 충실 | ○ 충실 |
| **종합** | **A+** | **A-** | **A** |

---

## 1. GPT-5.2 (OpenAI) — 19.7s

### Headline
> 2471일째, DLBCL 표적 ADC는 국내 미허가

### Subtitle
> CD79b ADC pola | glofitamab·loncastuximab도 국내 진입 대기

### Key Points
1. 재발·불응성 DLBCL에서 CD79b에 결합→세포 내로 유입→MMAE 방출→미세소관 파괴→종양세포 사멸을 유도하는 항체약물접합체(ADC)
2. FDA가 2019-06-10 승인한 뒤 EMA도 2020-01-16 승인했다. 그래서 약제팀은 글로벌 표준 치료 변화가 국내 공백으로 이어지는지 점검해야 한다.
3. 국내는 식약처 허가 문턱을 넘지 못해 처방이 불가하다. 그래서 현재는 급여 논의 자체가 불가능하고, 환자는 전액 부담 경로만 남는다.
4. 경쟁축인 GLOFITAMAB(CD20×CD3)과 LONCASTUXIMAB TESIRINE(CD19 ADC)도 국내 도입이 'expected'로 묶여 있다. 그래서 국내 후속 파이프라인의 동시 진입 여부가 병원 약제 전략의 변수다.

### Global Section
2471일. 글로벌 승인 이후 이 약이 한국에서 '공급 공백'으로 남은 시간이다. Polatuzumab vedotin은 재발·불응성 DLBCL에서 B세포 표면 CD79b를 표적해 MMAE를 종양세포 안으로 전달한다. 즉, **항체가 표적을 찍고 독성 payload가 내부에서 작동**하는 구조다.

- **Polatuzumab vedotin**: CD79b ADC, 표적 전달로 세포독성을 집중
- **GLOFITAMAB**: CD20×CD3 이중특이, T세포를 종양에 연결
- **LONCASTUXIMAB TESIRINE**: CD19 ADC, B세포 항원 다른 축을 공략

경쟁 지형은 'ADC vs 이중특이'로 갈린다. 그래서 기관별로 입원·주사실 운영, CRS 대응 같은 운영 리소스까지 포함해 비교해야 한다. 다만 POLARIX에서 OS는 유의차에 도달하지 못했고(HR 0.94, 95% CI 0.69–1.28), CR률도 58%로 동일했다. 그래서 약제위원회는 PFS 개선만으로 채택 근거가 충분한지, 가치평가 프레임을 먼저 정해야 한다.

### Domestic Section
국내에서는 식약처 미허가로 처방 자체가 막혀 '급여 이전 단계'에 머물러 있다. 글로벌 승인 후 6년 9개월이 지난 만큼, 병원은 단기 도입 가정이 아닌 **허가 전 접근 시나리오**를 기준으로 환자 상담 체계를 설계해야 한다.

- **Polatuzumab vedotin**: 미허가로 원내 처방 불가
- **GLOFITAMAB**: 국내 'expected' 상태, 도입 시 면역독성 운영 준비 필요
- **LONCASTUXIMAB TESIRINE**: 국내 'expected' 상태, ADC 계열 안전성·투여 프로토콜 정비 필요

현재 CRIS에 등록된 국내 임상이 0건이라, '임상 참여' 경로는 당장 작동하지 않는다. 그래서 환자 의뢰가 들어오면 긴급도입·EAP 같은 제도 경로 안내가 실무의 중심이 된다. 향후 등재가 이뤄지면 암환자 산정특례 5% 적용 여지가 있다. 그래서 약제팀은 허가 신호가 포착되는 즉시, 산정특례 등록 흐름까지 포함한 원스톱 안내문을 준비해야 한다.

### MedClaim Section
현재 국내 미허가로 원내 처방·청구는 불가하다. 그래서 환자 요청이 발생하면 '허가 전 접근' 절차를 표준화해야 한다.

- KODC 긴급도입: 개별 신청 경로로 전액 환자 부담이 전제된다. 그래서 의무기록에 임상적 필요성과 대체치료 한계를 명확히 남겨야 한다.
- 제약사 EAP/Named Patient Program: 프로그램 유무가 접근성을 좌우한다. 그래서 공급 가능 여부와 예상 소요기간을 RA/구매 파트가 먼저 확인해야 한다.

국내 임상시험 참여는 현재 등록 정보가 없어 선택지에서 제외해야 한다. 그래서 의료진 안내 시 '임상 참여 가능' 문구를 넣지 말아야 한다. 허가·급여가 추후 진행되면 암환자 산정특례(5%) 적용 가능성이 열리지만, 현재는 전액 비급여 구간이다. 그래서 약제팀은 긴급도입 안내서와 비용 고지 문서를 먼저 마련하는 것이 우선이다.

---

## 2. Gemini 2.5 Flash — 17.9s

### Headline
> 글로벌 승인 2471일, DLBCL ADC Polatuzumab Vedotin 국내 미도입 장기화

### Subtitle
> CD79b 표적 ADC, 재발·불응성 DLBCL 치료 지연 | 경쟁 약물도 국내 미허가

### Key Points
1. B세포 표면 CD79b에 결합하여 미세소관 억제제 MMAE를 방출, 종양세포 사멸 유도 — 기존 R-CHOP의 비선택적 세포독성 대비 표적 치료
2. FDA가 2019년 6월, EMA가 2020년 1월 승인 완료 — 전 세계 DLBCL 치료 패러다임 변화에 기여
3. 국내 MFDS 미허가, HIRA 비급여 상태 — 글로벌 승인 후 6년 9개월째 국내 환자 접근 불가능
4. GLOFITAMAB(이중특이항체), LONCASTUXIMAB TESIRINE(ADC) 등 경쟁 약물도 국내 미허가로 미충족 수요 심화

### Global Section
2471일. FDA와 EMA가 Polatuzumab Vedotin을 승인한 지 벌써 6년 9개월이 흘렀다. 이 약물은 B세포 표면의 CD79b에 선택적으로 결합하는 항체-약물 접합체(ADC)다. CD79b 결합 후 약물이 세포 내부로 유입되면, 강력한 미세소관 억제제인 MMAE(Monomethyl auristatin E)를 방출한다. 이 MMAE는 종양 세포의 미세소관 기능을 저해하여 세포 분열을 멈추고 사멸을 유도한다. 이는 비선택적 세포독성 항암제인 R-CHOP 요법과 차별화된다.

재발 또는 불응성 미만성 거대 B세포 림프종(DLBCL) 환자를 대상으로 한 POLARIX 3상 임상시험에서 Polatuzumab Vedotin + R-CHP 병용 요법은 R-CHOP 대비 질병 진행 또는 사망 위험을 27% 감소시켰다 (PFS HR 0.73, 95% CI 0.57–0.95, p=0.02).

- **Polatuzumab Vedotin (CD79b ADC)**: 1차 치료(pola-R-CHP)로 확장, PFS 개선
- **GLOFITAMAB (CD20×CD3 이중특이항체)**: 고정 기간 투여, 단독 요법
- **LONCASTUXIMAB TESIRINE (CD19 ADC)**: 단독 요법, 3차 이후

다만 POLARIX 시험에서 OS(전체생존기간) 차이는 통계적 유의성에 도달하지 못했고(HR 0.94, 95% CI 0.69–1.28), CR(완전관해)률도 양 군 58%로 동일했다. PFS 개선이 장기 생존으로 이어지는지는 추가 추적이 필요하다.

### Domestic Section
글로벌 승인 후 6년 9개월이 경과했음에도, Polatuzumab Vedotin은 국내에서 아직 허가 문턱을 넘지 못하고 있다. 이로 인해 재발·불응성 DLBCL 환자들은 새로운 표적 치료 옵션에 대한 접근이 원천 차단된 상태다.

- **Polatuzumab Vedotin**: MFDS 미허가 (장기 미허가 상태)
- **GLOFITAMAB**: 국내 허가 '예정' 상태 (MFDS 심사 중이거나 신청 준비 단계 추정)
- **LONCASTUXIMAB TESIRINE**: 국내 허가 '예정' 상태 (MFDS 심사 중이거나 신청 준비 단계 추정)

CRIS(국가임상시험등록사업)에 등록된 국내 임상시험이 없어, MFDS 허가 신청 및 심사 진행 여부를 확인하기 어렵다. 이는 국내 판매권자 부재 또는 시장성 판단 보류로 해석될 수 있다.

### MedClaim Section
현재 Polatuzumab Vedotin은 국내 미허가 약물이므로 처방 자체가 법적으로 불가하다. 환자가 전액을 부담해야 하는 비급여 구간에 놓여 있다.

- **KODC 긴급도입**: Polatuzumab Vedotin이 희귀의약품으로 지정될 경우, 한국희귀·필수의약품센터(KODC)를 통한 긴급도입을 고려할 수 있다. 이 경우 환자는 전액을 부담해야 한다.
- **제약사 EAP/NPP**: 로슈(Roche)의 해외 환자 지원 프로그램(EAP) 또는 의사 주도 Named Patient Program(NPP)의 국내 개설 여부를 주기적으로 확인해야 한다.

약제팀은 재발·불응성 DLBCL 치료를 위한 글로벌 혁신 약물 3종(Polatuzumab Vedotin, GLOFITAMAB, LONCASTUXIMAB TESIRINE)의 국내 허가 진행 상황과 판매권자 확보 동향을 지속적으로 추적하고, 긴급도입 신청 절차 및 필요 서류를 사전에 준비해야 한다.

---

## 3. Gemini 3 Flash Preview — 19.7s

### Headline
> DLBCL 1차 표준 치료 바꾼 ADC, 글로벌 승인 7년째 국내 도입 '안갯속'

### Subtitle
> CD79b 표적 polatuzumab vedotin | PFS 위험 27% 감소에도 2,471일간 국내 미허가

### Key Points
1. B세포 표면 CD79b에 결합해 세포독성 물질 MMAE를 방출, 미세소관을 파괴하여 종양세포 사멸을 유도하는 기전
2. FDA 승인 후 2,471일 경과 — POLARIX 임상에서 PFS HR 0.73(p=0.02)으로 R-CHOP 대비 우월성 입증
3. 국내 MFDS 미허가 및 HIRA 비급여 상태 — 글로벌 표준 치료제로 자리 잡은 지 6년 9개월째 진입 전무
4. GLOFITAMAB(이중특이항체), LONCASTUXIMAB(ADC) 등 차세대 치료제와의 경쟁 구도 형성 전 도입 시급성 증대

### Global Section
2,471일 전 FDA가 Polatuzumab vedotin을 승인한 이후, 이 ADC는 DLBCL 치료의 핵심 포트폴리오로 자리 잡았다. 이 약물은 B세포 표면의 CD79b와 결합 → 세포 내 MMAE 방출 → 미세소관 형성 차단 → 종양세포 사멸로 이어지는 정밀 타격 기전을 갖는다. 기존 R-CHOP이 비선택적 세포독성을 보이는 것과 달리, 표적 전달을 통해 치료 효율을 높였다.

- **Polatuzumab Vedotin**: CD79b ADC, 1차 병용(Pola-R-CHP)에서 PFS HR 0.73 달성
- **Glofitamab**: CD20xCD3 이중특이항체, 2차 이상에서 고정 기간 투여 방식
- **Loncastuximab Tesirine**: CD19 ADC, 3차 이상 단독 요법으로 활용

다만 POLARIX 시험에서 OS(전체생존기간) 차이는 통계적 유의성에 도달하지 못했으며(HR 0.94, 95% CI 0.69–1.28), CR(완전관해)률도 양 군 모두 58%로 동일했다. PFS 개선이 실질적인 장기 생존 이득으로 이어지는지에 대해서는 향후 추가적인 데이터 업데이트가 필요하다.

### Domestic Section
글로벌 양대 규제기관인 FDA와 EMA가 승인한 지 6년 9개월이 흘렀으나, 국내 환자들은 여전히 허가라는 문턱조차 넘지 못하고 있다. Polatuzumab vedotin은 현재 국내에서 미허가 상태로 남아 있어 재발·불응성 DLBCL 환자들의 미충족 수요가 극심한 상황이다.

- **현황**: MFDS 미허가(글로벌 승인 후 2,471일 경과)
- **경쟁 구도**: GLOFITAMAB 등 후속 약물들도 국내 도입 대기 중

국내 임상시험 정보시스템(CRIS)에 등록된 관련 임상이 전무하다는 점은 단기간 내 국내 허가 전환 가능성이 낮음을 시사한다. 경영진은 글로벌 표준 요법과 국내 진료 지침 간의 간극이 벌어지고 있는 점을 고려하여, 대체 약물 도입 시나리오를 검토해야 한다.

### MedClaim Section
현재 국내 미허가 상태로 법적인 공식 처방 및 보험 급여 청구가 원천적으로 불가능하다.

- **KODC 긴급도입**: 희귀의약품 지정 시 한국희귀·필수의약품센터를 통한 개별 신청 및 전액 환자 부담 도입 검토
- **제약사 EAP**: 판매권자인 로슈(Roche)의 인도주의적 지원 프로그램(Named Patient Program) 운영 여부 확인
- **액션 아이템**: DLBCL 치료 옵션 공백에 따른 환자 민원에 대비하여 긴급도입 절차와 고액의 비용 부담(100% 자부담)을 원무/상담팀에 사전 공유

약제팀에서는 동일 적응증의 경쟁 약물인 Glofitamab 등의 국내 허가 동향을 비교 추적하여, 치료 옵션의 우선순위를 재설정해야 한다.
