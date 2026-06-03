# 001 — 모듈 아키텍처 설계

## 0. 대전제

- **모듈러 모놀리스** (Modular Monolith). 마이크로서비스 ❌ — 그건 경량화 원칙에 정면 위배.
  → 배포는 **단일 프로세스**, 내부는 **엄격히 분리된 모듈**. 나중에 필요하면 모듈 단위로 떼어낼 수 있게 경계만 깨끗이.
- **핵심 통찰:** 우리는 이미 "도구-우선(agentic core)"으로 정했다. 그러면 **각 모듈의 공개 서비스 API = 사람도(UI) AI도(도구) 호출하는 단일 진입점**. 모듈화와 AI 도구화는 *같은 작업*이다.

---

## 1. 모듈 지도

| 모듈 | 책임 | 다른 모듈에 노출하는 핵심 API |
|---|---|---|
| **core** | DB세션, **이벤트버스**, 설정, money/decimal, 감사로그, base 모델 | (인프라 — 모두가 의존) |
| **auth** | 사용자·세션·역할·권한 | `get_current_user`, `has_permission` |
| **hr** | 직원·조직·**보고라인(reports_to)** | `get_approval_chain(employee_id)`, `get_employee` |
| **approval** | 결재요청·규칙·**라우팅 엔진** | `submit_request`, `approve`, `reject` |
| **procurement** | 거래처·발주(PO) | `create_po`, `get_po` |
| **inventory** | 품목·재고·입고·출고·시리얼·**이동평균** | `post_inbound`, `post_outbound`, `get_stock` |
| **assets** | 고정자산·감가상각·**재고↔자산 전환** | `create_asset`, `run_depreciation`, `reclassify` |
| **sales** | 고객·수주(SO)·AR인보이스·수금 (매입측 거울) | `create_so`, `post_ar_invoice`, `post_receipt` |
| **expense** | 경비/정산(Non-PO 지출)·직원 환급 | `submit_expense`, `reimburse` |
| **bank** | 은행계좌·**월간 statement 업로드 대사** | `import_statement`, `reconcile` |
| **accounting** | COA·전표·기간(마감)·AP(3-way)·지급·**posting 엔진**·재무제표 | `post_journal`, `generate_financials`, `match_ap_bill` |
| **documents** | 첨부파일·OCR/파싱 | `store_document`, `parse_document` |
| **ai** | 에이전트 오케스트레이터·**도구 레지스트리**·LLM(Ollama)·RAG·대화 | (최상위 — 다른 모듈의 도구를 호출) |

> **의존 방향 규칙:** 위→아래로만 의존. 회계는 재고를 모른다(역방향 금지). 재고가 회계를 직접 부르지도 않는다 → **이벤트로 연결**(아래 §3).

---

## 2. 모듈 내부 구조 (모든 모듈 동일 골격)

```
inventory/
  __init__.py     # 모듈 등록: 라우트 + 이벤트핸들러 + AI도구
  models.py       # 🔒 PRIVATE — 다른 모듈이 절대 import 금지
  schemas.py      # DTO (Pydantic) — 공개 계약(contract) 타입
  service.py      # ✅ 공개 API — 외부 진입점은 오직 여기
  events.py       # 이 모듈이 발행하는 이벤트 정의
  handlers.py     # 다른 모듈 이벤트 구독·반응
  tools.py        # AI 도구 (service.py의 얇은 래퍼)
  routes.py       # UI/HTTP (얇게 — service만 호출)
```

**철칙:**
1. `routes`도 `tools`도 `models`를 직접 안 만진다 → 항상 `service` 경유.
2. 모듈 밖에서는 **남의 `models.py`/테이블을 직접 못 본다.** 오직 그 모듈 `service.py`의 함수 + `schemas.py`의 DTO만.
3. `service.py`가 곧 그 모듈의 "API 명세"다. (사람=routes가 호출, AI=tools가 호출, 타모듈=직접 호출 — **같은 함수**)

---

## 3. 모듈 간 연동 — 두 가지 메커니즘

연동을 헷갈리지 않는 단 하나의 규칙:

> **무언가 *필요해서* 가져오거나 시킬 때 = 직접 서비스 호출** (상대를 안다)
> **무언가 *일어났고* 누가 반응하든 상관없을 때 = 이벤트 발행** (상대를 모른다)

### (A) 동기 호출 — Command / Query

상대 모듈이 누군지 알 때. 예: 결재 라우팅이 조직도가 필요 →
```python
# approval/service.py
chain = hr.service.get_approval_chain(drafter_employee_id, levels=2)
```
- 타입 있는 DTO로 주고받음. 상대 테이블 직접 조회 ❌.

### (B) 도메인 이벤트 — Reaction (★ 회계 연동의 핵심)

재고/자산/구매에서 *돈 움직이는 일*이 생기면, 그 모듈은 **누가 듣는지 모른 채 이벤트만 발행**한다. 회계가 구독해서 전표를 만든다.

```
inventory.post_inbound()  ─emit→  InboundPosted{lines:[{product_type, qty, cost}]}
                                        │
                  ┌─────────────────────┼──────────────────────┐
            accounting.handlers      assets.handlers       (audit/RAG 색인…)
            → posting 엔진으로          → asset-type 라인은
              전표 생성                   FixedAsset 자동 등록
```

**이게 왜 결정적인가:** 재고 모듈은 **GL 계정코드를 1도 모른다.** "어떤 거래가 어느 계정으로 분개되는가"는 오직 회계 모듈이 안다. 재고는 "입고가 일어났다"만 알린다. → 재고/구매/자산을 건드려도 회계 로직이 안 깨지고, 회계 규칙을 바꿔도 재고 코드는 그대로.

**트랜잭션 경계:** 이벤트는 **동일 DB 트랜잭션 안에서 동기 디스패치**한다. 입고+전표+자산등록이 **all-or-nothing**으로 커밋. (Celery/Redis 같은 비동기 큐 불필요 — 경량 유지, 정합성 보장.)

---

## 4. Posting 엔진 — 회계 연동의 단일 지점

모든 자동분개가 통과하는 **하나의 규칙 테이블**. 계정 매핑 지식이 여기 한 곳에만 산다.

| event_type | 조건(product_type 등) | 차변 | 대변 |
|---|---|---|---|
| inbound.posted | inventory | Inventory | GR/IR |
| inbound.posted | asset | Fixed Asset | GR/IR |
| ap_bill.matched | — | GR/IR | AP |
| outbound.posted | sale | COGS | Inventory |
| reclass | inv→asset | Fixed Asset | Inventory |
| reclass | asset→inv | Inventory + 감가누계 | Fixed Asset |
| depreciation.run | — | 감가상각비 | 감가누계 |
| ar_invoice.posted | — | AR | Revenue + Sales Tax Payable |
| receipt.posted | — | Bank/Cash | AR |
| expense.approved | category별 | 비용계정 | Employee Payable |
| reimburse.posted | — | Employee Payable | Cash |
| bank.unmatched | category별 | 수수료/이자 등 | Bank |

- **테이블 주도(설정형)** → admin이 계정 매핑을 바꿔도 코드 수정 불필요. QB 대체 시 유연성 확보.
- AI도 이 엔진을 거치므로, AI가 만든 전표도 사람이 만든 것과 **정확히 같은 규칙**을 따른다.

---

## 5. AI 레이어가 얹히는 방식

```
        ┌────────────── ai 모듈 (오케스트레이터) ──────────────┐
        │  대화 → LLM(Ollama) → 도구선택 → 도구실행 → 응답       │
        └──────────────────────┬──────────────────────────────┘
                               │ 도구 = 각 모듈 tools.py
                               ▼
   inventory.tools / accounting.tools / approval.tools / hr.tools ...
                               │ (얇은 래퍼)
                               ▼
                  각 모듈 service.py  ← UI(routes)도 같은 걸 호출
```

- **도구 레지스트리:** 각 모듈이 `tools.py`에서 자기 도구를 등록 → `ai` 모듈이 수집 → LLM에 function schema로 제공.
- 새 기능 추가 = service에 함수 추가 + tools에 한 줄 등록 → **사람 UI와 AI가 동시에** 그 기능을 얻음.
- **불확실성 게이팅(§8.2)**·감사로그도 ai 오케스트레이터 + service 레벨에서 일괄 적용.

---

## 6. 한 장 요약

1. 단일 프로세스, 내부는 엄격 분리(모듈러 모놀리스).
2. 모듈의 유일한 문 = `service.py`. 남의 models 직접 접근 금지.
3. 연동: **필요하면 직접 호출 / 반응이면 이벤트**.
4. 회계는 **이벤트 구독 + posting 규칙 테이블**로만 붙는다 → 완전 디커플.
5. AI 도구 = service의 얇은 래퍼 → 사람과 AI가 같은 API.
6. 이벤트는 같은 트랜잭션에서 동기 → 정합성 + 경량 동시 달성.
