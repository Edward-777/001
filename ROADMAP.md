# 001 — 로드맵 (Phase 1 상세)

> [OVERVIEW.md](OVERVIEW.md) 로드맵의 작업 단위 분해. 빌드 순서 = **의존성 + "척추 먼저"** 원칙.
> 원칙: 먼저 **스파인**(스캐폴드→권한→회계코어+posting→이벤트 수직슬라이스 1개)을 세워 아키텍처를 증명하고, 그 다음 모듈을 부챗살로 확장.

---

## Phase 1 — 경량 코어 (전 회계 사이클, AI 없이 수동 동작)

| M | 마일스톤 | 핵심 산출물 | 수용 기준(done) |
|---|---|---|---|
| **M0** | 프로젝트 스캐폴드 | repo 구조, config, DB세션, **이벤트버스**, base 모델, doc_sequences, audit_log, app factory, /health | `uvicorn`으로 떠서 /health 200. 이벤트버스 단위테스트 통과 |
| **M1** | 인증 + 권한 3축 | users, user_scopes, 세션 로그인, **권한 게이트**(scope×level×boundary 판정식) | 로그인 가능. 권한 판정 함수 테스트(연봉=hr3 차단 케이스 포함) |
| **M2** | HR/조직도 | departments, employees, reports_to | 직원 등록·보고라인 트리. `get_approval_chain()` 동작 |
| **M3** | 마스터데이터 + COA 시드 | vendors, customers, products, accounts(+QuickBooks COA 시드), 룩업(카테고리/tax) | COA 시드 로드. CRUD 동작 |
| **M4** | **회계 코어 + posting 엔진** ★ | journal_entries/lines(차=대 불변식), 설정형 posting 규칙테이블, accounting_periods(마감) | 수동 전표 posting·역분개·마감 동작. posting 규칙 단위테스트 |
| **M5** | 결재 워크플로우 | requests, approval_lines, approval_rules, **조직도 라우팅 엔진** | 기안→상신→조직도 결재선 자동→승인/반려 |
| **M6** | 구매(스파인 슬라이스) | purchase_orders (승인된 request에서 생성) | 승인→PO 자동생성 |
| **M7** | **재고 + 이벤트 연동 증명** ★ | inbounds, stock_movements/balances(이동평균), serials. `InboundPosted` 이벤트→회계 자동분개 | 입고 posting → 재고 갱신 **+ 전표 자동**(같은 트랜잭션). 아키텍처 검증 완료 |
| **M8** | 자산 | fixed_assets, depreciation, **재고↔자산 전환** | 자산입고·월감가·양방향 전환 분개 |
| **M9** | 출고 + 매출/AR | outbounds, sales_orders, ar_invoices, receipts | 판매출고(COGS)+AR인보이스(매출·세금)+수금 분개 |
| **M10** | AP 3-way match | ap_bills, ap_bill_lines, payments | PO↔입고↔인보이스 매칭, GR/IR clearing, 지급 |
| **M11** | 경비 정산 | requests(type=expense) 확장 + reimbursement | 출장경비→결재→환급채무→지급 |
| **M12** | 은행 대사 | bank_accounts, statement 업로드(파서는 수동/CSV 먼저), reconcile | statement 라인↔전표 매칭, 미매칭 신규전표 |
| **M13** | 리포트 | BS/IS/CF/TB/GL/AP·AR aging/재고평가 (전표에서 산출) | "1월 마감자료"= generate_financials 동작 |
| **M14** | 횡단 | notifications+SSE, documents 레지스트리(AI 전), 야간 백업 | 결재알림 실시간, 백업·복원 |
| **M15** | UI | HTMX/Jinja2/Tailwind 화면(목록·폼·대시보드), 반응형/PWA | 사람이 전 사이클을 화면으로 수행 |

**Phase 1 완료 정의:** AI 없이 사람이 화면으로 *기안→결재→구매→입고→재고/자산→출고→매출/AR→경비→은행대사→마감→재무제표* 전 사이클을 돌릴 수 있고, 모든 거래가 자동 복식부기로 장부에 남는다.

---

## Phase 2~ (요약)
- **P2 에이전트 연결 ✅:** Ollama+도구레지스트리+에이전트 루프. 권한게이트·불확실성게이팅. 출장 시나리오.
- **P3 문서파싱·분류·RAG ✅:** 수신분류 파이프라인(§8.4), RAG 권한필터 질의, 비전 인보이스 파싱.
- **GTM 온보딩 (부분):** QBO export 임포트(`scripts/import_qbo` — COA+저널, posting 앵커/룰 자동 시드). 기초잔액·AI 계정매핑은 후속.
- **P4 파인튜닝:** 행동 LoRA + eval 하네스 + 데이터셋/eval 버전관리. (미착수)

---

## D6 — 자율 운영 에이전트 군단 (진행 중)

> 설계·구현 상세 = [docs/AGENT-FLEET.md](docs/AGENT-FLEET.md). `fleet` 모듈 + `/fleet`·`/sales` 화면.

| 마일스톤 | 내용 | 상태 |
|---------|------|------|
| F1 | 작업큐(`fleet_tasks`) 모델 + 상태머신(중복방지·반송·에스컬레이션) | ✅ |
| F2 | 디스패처 (분류→롤 라우팅) | ✅ |
| F3 | 💸지출·AP 롤 핸들러 + 단일 작업 루프 (드래프트→승인→기표) | ✅ |
| F4 | 승인 인박스 UI + 업로드→디스패처 + APScheduler 틱 | ✅ |
| F5 | 📊자금·인사이트 (런웨이·번레이트·살여유) + AI 도구 | ✅ |
| F6 | 💰매출·수금 롤 (고객 청구서 드래프트→승인→매출인식) | ✅ |
| F7 | 주간 결제목록(payment run) → 승인 시 지급 분개 | ✅ |
| F8 | ⚠️이상탐지(지출 급증·중복) + 일일 인박스 알림 | ✅ |
| F9 | 📅월마감 제안 → 승인 시 기간 잠금 | ✅ |
| F10 | 인사이트 대시보드 카드 + 인박스 카운트 | ✅ |
| F11–13 | 수주→현금(O2C): 견적·출하 모델 + 풀필먼트 서비스 + 문서(견적/패킹/인보이스) + `/sales` 파이프라인 UI | ✅ |
| — | 📧이메일 커넥터(Gmail OAuth) · 선택 롤(people/supply/docs/support) · 분류기 확장 | 후속 |

**불변식:** 전 롤 항상 가용(단일 루프가 롤 갈아입으며 처리) · 드래프트-우선 · 결과 큰 행동(기표·지급·발송·마감)은 사람 승인 게이트 · 회사 데이터 외부 유출 0.

**코드리뷰 하드닝(외부 리뷰 반영):** 플릿 변경 라우트 전부 finance L3 게이트 · 문서 Default-Deny(분류실패→최제한) · 리포트 perms 단일 진실원천 · 임포터 per-JE 균형 단언 · LLM 장애 그레이스풀. **후속 = eval 하네스 · 승인 피로 대책(인박스 위험순 정렬) · Alembic 마이그레이션 재생성.**

---

## 빌드 순서의 논리 (왜 이 순서인가)
1. **M0~M1**(스캐폴드·권한)이 *모든 것의 전제*. 권한은 나중에 끼우면 전부 갈아엎음 → 처음부터.
2. **M4 회계 코어 + posting 엔진**이 *중력 중심*. 이후 모든 모듈이 여기로 이벤트를 쏨.
3. **M7**에서 "입고→이벤트→자동분개"를 처음 관통 → **아키텍처(이벤트+posting 디커플)가 실제로 도는지 증명.** 여기 통과하면 나머지 모듈은 같은 패턴 복제.
4. UI(M15)는 service가 다 선 뒤 얇게 — service가 정본이므로 UI는 후순위 가능.
