# 메드클레임 2.0 벤치마크 스크랩북

> 회의 요구사항별 실제 서비스 사례 + 캡처 가이드
> 팀 공유용 (기획팀·은빈님 참고)

---

## 사용법

각 벤치마크 서비스마다 **[캡처 대상]** 섹션이 있습니다.
표시된 URL에 접속해서 해당 화면을 캡처하면 됩니다.
캡처한 이미지는 `project/medclaim/research/screenshots/` 폴더에 저장해주세요.

---

## 1. Perplexity AI — 검색 + 정보 피드 결합

**우리가 가져올 것:** 검색창 + Discover 피드가 한 화면에 공존하는 구조

### 서비스 개요
- AI 기반 검색 엔진. 검색하면 여러 소스를 종합해 답변 + 출처 인용
- 홈 화면에 검색창과 함께 **Discover 피드**(큐레이션된 트렌딩 뉴스/콘텐츠) 배치
- 답변 하단에 Follow-up 질문 버튼 → 추가 탐색 유도

### UI 구조 상세
- **홈 화면 상단**: 중앙 정렬 검색창 + Focus 모드 선택 (All, Academic, Writing 등)
- **홈 화면 하단**: Discover 피드 — 카테고리별 트렌딩 토픽, 뉴스 카드
- **Discover 개인화**: 프로필에서 관심 키워드·역할·목표 설정 → 피드가 맞춤 큐레이션
- **답변 화면**: 소스 인용 번호가 답변 텍스트에 인라인 표시, 하단에 출처 링크 목록
- **Spaces**: 주제별 연구 허브 — 관련 검색·파일·지시사항을 그룹화

### 메드클레임 적용 포인트
| Perplexity 요소 | 메드클레임 적용 |
|-----------------|----------------|
| Discover 피드 | 최신 행정예고·개정 고시·삭감 사례 카드 |
| Focus 모드 | [심사지침] [고시·법령] [사례] 등 검색 범위 칩 |
| Follow-up 질문 | "관련 급여 기준도 확인하시겠어요?" 후속 질문 제안 |
| Spaces | 병원별/진료과별 연구 공간 |
| 개인화 피드 | 병원·직무·진료과 기반 맞춤 콘텐츠 |

### [캡처 대상]
| # | 화면 | URL | 캡처 포인트 |
|---|------|-----|------------|
| 1 | 홈 (검색 + Discover) | https://www.perplexity.ai/ | 검색창과 하단 피드가 한 화면에 있는 구조 |
| 2 | Discover 피드 | https://www.perplexity.ai/discover | 카드형 뉴스 피드 레이아웃 |
| 3 | 답변 화면 (인용) | 아무 질문 검색 후 | 인라인 출처 번호 + 하단 소스 링크 |
| 4 | Spaces | https://www.perplexity.ai/spaces | 주제별 연구 허브 구조 |

### 참고 가이드 (스크린샷 포함 워크스루)
- [How to Use Perplexity AI (2025): Screenshots, Citations & Setup](https://www.byriwa.com/how-to-use-perplexity-ai/)
- [Perplexity AI Complete Guide 2026](https://ai-basics.com/perplexity-ai-the-complete-beginners-guide/)
- [LearnPrompting — Complete Guide](https://learnprompting.org/blog/guide-perplexity)
- [Perplexity Getting Started](https://www.perplexity.ai/hub/getting-started)

---

## 2. Glean — 엔터프라이즈 AI 검색 포털

**우리가 가져올 것:** 새 탭 = 업무 커맨드 센터, 추천 문서 자동 노출

### 서비스 개요
- 사내 모든 앱(Slack, Drive, Teams 등) 통합 AI 검색 플랫폼
- 브라우저 새 탭을 **업무 커맨드 센터**로 전환
- Fast Company 2025 "World's Most Innovative Companies" 선정

### UI 구조 상세
- **새 탭 페이지**: 접속 즉시 개인화된 추천 문서, 캘린더, 알림 노출
- **통합 검색**: 문서·대화·전문가를 탭 이동 없이 검색
- **Discover 탭**: 현재 보고 있는 화면 기반으로 관련 프롬프트·리소스·전문가 자동 추천
- **사이드바**: Cmd+J / Alt+J로 어디서든 열리는 AI 어시스턴트 사이드바
- **Quick Chat**: 항상 떠 있는 경량 채팅 창 — 코드 리뷰, 문서 작성 중 바로 질문
- **Screenshot-to-chat**: 화면 캡처 → AI에게 보여주고 질문

### 메드클레임 적용 포인트
| Glean 요소 | 메드클레임 적용 |
|-----------|----------------|
| 새 탭 커맨드 센터 | 로그인 즉시 "오늘의 변경사항" 대시보드 |
| 추천 문서 | "OOO 병원 맞춤형 최신 고시" 자동 노출 |
| Discover 탭 | 현재 조회 중인 심사 기준 관련 추천 |
| 사이드바 | EMR 화면에서 바로 열리는 간편 질문창 (장기 목표) |

### [캡처 대상]
| # | 화면 | URL | 캡처 포인트 |
|---|------|-----|------------|
| 1 | 브라우저 확장 소개 | https://www.glean.com/browser-extension | 새 탭 페이지 + 사이드바 제품 이미지 |
| 2 | 제품 개요 | https://www.glean.com/product/overview | 검색 + Assistant + Canvas 화면 |
| 3 | Chrome 웹스토어 | https://chromewebstore.google.com/detail/glean/cfpdompphcacgpjfbonkdokgjhgabpij | 스토어 스크린샷 (실제 UI 확인 가능) |
| 4 | 데스크톱 앱 소개 | https://www.glean.com/blog/glean-desktop-nov-drop-2025 | Quick Chat, 사이드바 UI |

---

## 3. Harvey AI — 법률 AI (신뢰성 + 톤앤매너)

**우리가 가져올 것:** Citation 시스템, Split View(답변+원문), 네이비/그레이 톤

### 서비스 개요
- 변호사 전용 AI. 기업가치 $8B (2025.12 시리즈F)
- 핵심 설계 원칙: **가독성 + 인용(Citation)** — 화려함 < 정확함
- 5개 핵심 도구: Assistant, Knowledge, Vault, Workflows, History

### UI/Citation 구조 상세
- **Assistant**: 자연어 질의 → AI 답변 + 근거 문서 인용 링크
- **Source Assured**: 모든 답변이 신뢰할 수 있는 인용 자료에 기반
- **Citation 시스템**: 구조화된 메타데이터 추출 + 임베딩 기반 검색 + LLM 문서 매칭
  - 답변 내 인용 번호 → 클릭 시 원문 해당 부분으로 이동
  - LexisNexis 통합으로 실시간 판례 유효성 검증
- **문서 업로드**: 최대 50개 문서 동시 분석, 문서 기반 답변 생성
- **Draft Mode**: 장문 법률 문서 초안 작성 + 반복 수정
- **성능**: 할루시네이션 60% 감소, 인용 정확도 23% 향상 (2025 업데이트)
- **Microsoft Word 직접 연동**: Word 안에서 Harvey 사용 가능

### 메드클레임 적용 포인트
| Harvey 요소 | 메드클레임 적용 |
|------------|----------------|
| Split View | 좌: AI 요약 / 우: 심평원 원문 고시(PDF) |
| Citation 번호 | 답변 내 [1][2] 클릭 → 원문 해당 부분 하이라이트 |
| Source Assured | 모든 답변에 "근거: OO 고시, 개정일: YYYY-MM-DD" 표시 |
| 네이비/그레이 톤 | 전문성·신뢰감 있는 컬러 시스템 |
| 할루시네이션 감소 | Citation 기반 검증 프로세스 벤치마크 |

### [캡처 대상]
| # | 화면 | URL | 캡처 포인트 |
|---|------|-----|------------|
| 1 | 제품 메인 | https://www.harvey.ai/ | 전체 톤앤매너, 네이비/다크 컬러 기조 |
| 2 | Assistant 소개 | https://www.harvey.ai/platform/assistant | Source Assured, 문서 분석 UI 이미지 |
| 3 | 제품 데모 영상 | YouTube에서 "Harvey AI demo" 검색 | 실제 Split View + Citation 패널 동작 |
| 4 | 기능 분석 블로그 | https://www.geeklawblog.com/2024/07/lets-breakdown-harvey-ais-video-of-features-guest-post.html | 영상 캡처 기반 기능 분석 |

> **참고**: Harvey AI는 엔터프라이즈 전용이라 공개 스크린샷이 거의 없음.
> YouTube "Harvey AI demo", "Harvey AI walkthrough"로 검색하면 데모 영상에서 실제 UI 확인 가능.

---

## 4. Shopify Admin — 업무 대시보드 + Greeting

**우리가 가져올 것:** "안녕하세요 OOO님" 인사 위젯, 오늘의 업무 요약 카드

### 서비스 개요
- 전 세계 최대 이커머스 플랫폼의 관리자 대시보드
- 로그인 즉시 "오늘의 매출·주문·할 일" 요약 표시
- 맞춤 추천으로 스토어 개선 제안

### UI 구조 상세
- **Home 섹션**: 스토어 최근 활동 스냅샷 (매출, 트래픽, 주문)
- **실시간 데이터**: 성과 지표가 실시간 업데이트
- **맞춤 추천**: 실적 기반으로 "이걸 해보세요" 제안 카드
- **Polaris 디자인 시스템**: 일관된 컴포넌트 (Badge, Banner, Card, Button 등)
- **App Home 패턴**: "상태 업데이트 + 즉시 실행 가능한 액션" 우선 노출

### 메드클레임 적용 포인트
| Shopify 요소 | 메드클레임 적용 |
|-------------|----------------|
| Home 스냅샷 | "오늘 확인할 규정 변경 N건" 요약 |
| 맞춤 추천 | "귀원 삭감률 줄이기 위한 조치 제안" |
| 실시간 업데이트 | 심평원 공지 실시간 반영 |
| Polaris 컴포넌트 | Badge(상태), Banner(긴급알림), Card(정보블록) 패턴 참고 |

### [캡처 대상]
| # | 화면 | URL | 캡처 포인트 |
|---|------|-----|------------|
| 1 | Shopify Admin 가이드 | https://dodropshipping.com/shopify-admin-guide/ | 관리자 Home 화면 스크린샷 |
| 2 | Shopify Dashboard 가이드 | https://brainspate.com/blog/shopify-dashboard/ | 대시보드 레이아웃 스크린샷 |
| 3 | Polaris 디자인 시스템 | https://polaris.shopify.com/ | 카드·배지·배너 컴포넌트 참고 |
| 4 | App Home 패턴 | https://shopify.dev/docs/api/app-home/patterns/templates/homepage | 인사 위젯 + 상태 카드 패턴 |

---

## 5. Intercom — 개인화 Messenger + 업무 대시보드

**우리가 가져올 것:** 커스터마이즈 가능한 홈 화면, 카드형 앱 배치

### 서비스 개요
- B2B 고객 지원 플랫폼. Messenger 홈 화면을 "회사의 프론트 데스크"로 설계
- 대화 목록이 아닌 **앱 카드** 기반 홈 화면
- AI Copilot이 상담원에게 즉시 답변 제공

### UI 구조 상세
- **Messenger Home**: 커스터마이즈 가능한 홈 — 로고, 인사말, 앱 카드 배치
- **디자인 결정**: 대화 목록은 하나의 앱으로 격하 → 홈 화면의 주인공은 "앱 카드"
  - 95%의 대화가 24시간 내 종료 → 대화 목록 중심이 아닌 기능 중심 설계
- **모듈형 앱 시스템**: 도움말 검색, 데모 요청, 뉴스레터, 제품 공지 등을 카드로 배치
- **유연한 재구성**: 제품 출시·서비스 장애 등 상황에 따라 홈 화면 즉시 재배치
- **Inbox 개인화**: 팀원마다 Inbox 레이아웃 커스터마이즈 가능
- **우측 사이드바**: 고객 데이터 + Slack/Jira/Salesforce 연동 정보

### 메드클레임 적용 포인트
| Intercom 요소 | 메드클레임 적용 |
|-------------|----------------|
| 앱 카드 홈 | 기능별 카드(검색, 최신고시, 리포트, 즐겨찾기) 자유 배치 |
| 모듈형 구조 | 역할별(간호사/의사) 카드 구성 다르게 |
| 유연한 재구성 | 대규모 개정 시 "긴급 알림" 카드 최상단 배치 |
| Messenger 인사말 | "OOO님, 오늘 확인할 변경사항이 있습니다" |

### [캡처 대상]
| # | 화면 | URL | 캡처 포인트 |
|---|------|-----|------------|
| 1 | Messenger Home 설계 블로그 | https://www.intercom.com/blog/product-thinking-behind-messenger-home/ | 홈 화면 디자인 결정 과정 + UI |
| 2 | Messenger 커스터마이즈 | https://www.intercom.com/help/en/articles/6612589-set-up-and-customize-the-messenger | 인사말·로고·앱 카드 배치 화면 |
| 3 | Inbox | https://www.intercom.com/customer-service-platform/inbox | AI Copilot + 사이드바 레이아웃 |
| 4 | Figma 위젯 | https://www.figma.com/community/file/1017980872686116546/intercom-widget | 디자인 컴포넌트 참고 |

---

## 6. 추가 참고 — 디자인 영감 갤러리

실제 B2B SaaS / 헬스케어 대시보드 스크린샷을 대량으로 볼 수 있는 사이트:

| 사이트 | URL | 내용 |
|--------|-----|------|
| SaaSFrame | https://www.saasframe.io/categories/dashboard | SaaS 대시보드 UI 159개 |
| Dribbble (Health SaaS) | https://dribbble.com/tags/health-saas | 헬스케어 SaaS 디자인 모음 |
| Behance (SaaS Dashboard) | https://www.behance.net/search/projects/saas%20dashboard | B2B 대시보드 프로젝트 |
| Saaspo (Healthcare) | https://saaspo.com/industry/healthcare-saas-websites-inspiration | 헬스케어 SaaS 랜딩 27개 |
| KoruUX (Healthcare UI) | https://www.koruux.com/50-examples-of-healthcare-UI/ | 헬스케어 UI 50개 |

---

## 7. 컴플라이언스 특화 도구

메드클레임과 가장 유사한 "규제/컴플라이언스 추적" 도구:

### Softr Compliance Tracker
- URL: https://softr.io/create/compliance-tracker-dashboard
- 참고: 규정 상태 추적, 필터/정렬, 메타데이터(개정일·적용일) 표시 패턴

### VComply ComplianceOps
- URL: https://www.v-comply.com/
- 참고: HIPAA 등 규제별 자동 태스크 할당, 단일 대시보드에서 컴플라이언스 현황 추적
- 블로그: https://www.v-comply.com/blog/b2b-saas-compliance-overview/

---

## 참고 아티클 모음

### 대시보드 설계 원칙
- [6 Steps to Design Thoughtful Dashboards for B2B SaaS](https://uxdesign.cc/design-thoughtful-dashboards-for-b2b-saas-ff484385960d)
- [5 High-Impact SaaS Dashboard Examples for 2025](https://www.growthbi.com.au/post/5-high-impact-saas-dashboard-examples-for-2025)
- [SaaS Dashboard Templates (TailAdmin)](https://tailadmin.com/blog/saas-dashboard-templates)

### 헬스케어 UI
- [Healthcare Dashboard Portal Improves Visibility](https://blog.patoliyainfotech.com/healthcare-dashboard-portal-improves-visibility/)
- [50 Examples of Healthcare UI](https://www.koruux.com/50-examples-of-healthcare-UI/)

### Harvey AI 심층 분석
- [How Harvey Built Trust in Legal AI (Medium)](https://medium.com/@takafumi.endo/how-harvey-built-trust-in-legal-ai-a-case-study-for-builders-786cc23c3b6d)
- [Harvey AI Review 2025 (Purple Law)](https://purple.law/blog/harvey-ai-review-2025/)
- [Harvey Product Overview (MSBA)](https://www.msba.org/site/site/content/News-and-Publications/News/General-News/An_Overview_of_Harvey_AIs_Features_for_Lawyers.aspx)
- [Harvey Features Breakdown (3 Geeks Blog)](https://www.geeklawblog.com/2024/07/lets-breakdown-harvey-ais-video-of-features-guest-post.html)
