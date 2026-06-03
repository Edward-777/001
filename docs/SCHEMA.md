# 001 — 데이터 스키마 (D13)

> v0.1 초안. [DESIGN.md](../DESIGN.md) §5 도메인 모델의 필드 레벨 상세.
> 범위: **Phase 1 = 구매→재고→자산→회계 + 매출/AR + 경비정산 + 은행대사** (전 사이클).
> 표기: `PK`=기본키, `FK`=외래키, `enum(...)`=고정값 집합, money=USD `Numeric(15,2)`.
> 공통 컬럼(모든 테이블): `id PK`, `created_at`, `updated_at`, `created_by FK→users`.

---

## A0. 시스템 공통 (POLICIES)

### doc_sequences (gapless 채번 — §G10)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| doc_type | text | PO, JE, EXP, INV... |
| year | int | 연도별 |
| last_no | int | 마지막 번호. **트랜잭션 내 row lock으로 할당** |

### notifications (in-app 알림 — §G12)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| user_id | FK→users | 수신자 |
| type | text | approval/rejection/ai_question/bank/due... |
| title / body | text | |
| link | text | 클릭 시 이동 |
| is_read | bool | |
| created_at | timestamp | SSE로 실시간 푸시 |

### audit_logs (감사 추적 — AI/사람 공통, §G9·자율성)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| actor_user_id | FK→users | 행위자(AI 행위도 기록) |
| action | text | create/post/reverse/approve... |
| entity_type / entity_id | text/int | 대상 |
| detail_json | jsonb | 변경 내용·근거 문서 |
| at | timestamp | |

## A. 마스터 데이터

### users
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name | text | |
| email | text unique | 로그인 ID |
| password_hash | text | bcrypt |
| role | enum(employee, manager, accountant, admin) | 기본 scope 묶음 부여용 (POLICIES §G11) |
| department_id | FK→departments | nullable |
| is_active | bool | |
| → 실제 권한은 user_scopes로 세분 (DESIGN §8.5 — 3축) |

### user_scopes (권한 3축 — DESIGN §8.5)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| user_id | FK→users | |
| scope | enum(hr, finance, inventory, procurement, system) | ① 도메인 |
| level | int (1~3) | ② 등급 (예: hr 3=연봉) |
| data_boundary | enum(self, team, department, all) | ③ 데이터 경계(reports_to 트리 기준) |
| → 판정: user.level[scope] ≥ data.level AND 대상이 boundary 안(reports_to subtree) |

### departments
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name | text | |
| parent_id | FK→departments | 계층(nullable) |
| manager_employee_id | FK→employees | 부서장(기본 승인자 후보) |

### employees (HR/조직도 — 결재 라우팅의 토대)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| employee_no | text unique | |
| name | text | |
| department_id | FK→departments | 소속 조직 |
| position_title | text | 직책 |
| **reports_to_id** | FK→employees | **보고 라인(상급자)** ← 결재선이 이 체인을 타고 올라감 |
| hire_date | date | |
| status | enum(active, on_leave, terminated) | |
| user_id | FK→users | 로그인 계정 연결(nullable; 모든 직원이 시스템 사용자는 아님) |
| → 신입 등록 시 department+reports_to만 정하면 이후 결재선이 자동 형성 |

### vendors (매입처)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name | text | |
| tax_id | text | US EIN (1099용) |
| is_1099 | bool | 연말 1099 대상 |
| email / phone / address | text | |
| payment_terms | enum(due_on_receipt, net15, net30, net60) | AP 만기 계산 |
| is_active | bool | |

### products (품목)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| sku | text unique | |
| name | text | |
| model_name | text | 모델명 |
| type | enum(inventory, asset, consumable, service) | **자동분개 분기의 핵심** |
| track_serial | bool | true면 개체별 시리얼 추적 |
| unit | text | ea, box, hr... |
| category_id | FK→product_categories | nullable |
| standard_cost | money | 참고용 |
| default_expense_account_id | FK→accounts | 비용처리 시 기본 계정 |
| is_active | bool | |

### inventory_serials (시리얼 추적 — track_serial=true 품목)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| product_id | FK→products | |
| serial_no | text | 개체 고유번호 |
| status | enum(in_stock, sold, scrapped) | |
| unit_cost | money | 개체 취득원가 |
| inbound_line_id | FK→inbound_lines | 입고 출처 |
| outbound_ref | text | 출고/판매 시 |
| → 평가는 품목단위 이동평균 유지, 시리얼은 "어떤 개체가 재고에 있나" 추적용 |

### 룩업 테이블 (다른 곳에서 참조되는 분류 설정 — 설정형)
| 테이블 | 컬럼 | 비고 |
|---|---|---|
| **product_categories** | name, parent_id(nullable) | products.category_id가 참조 |
| **expense_categories** | name, default_expense_account_id FK→accounts | expense_lines.category_id 참조 → posting 규칙으로 비용계정 매핑 |
| **tax_codes** | name, rate(%), tax_account_id FK→accounts | ar_invoices.tax_code_id 참조. sales tax(주/지역별) |

### accounts (계정과목, QuickBooks식 COA)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| code | text unique | 예: 1200 |
| name | text | 예: Inventory Asset |
| type | enum(asset, liability, equity, revenue, expense) | |
| subtype | text | current_asset, fixed_asset, AP, COGS, expense... |
| parent_id | FK→accounts | 계층(nullable) |
| is_active | bool | |
| → 기본 COA를 시드로 제공 (US 소규모용 표준 세트) |

---

## B. 워크플로우 (기안 → 승인)

### requests (기안/품의)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| request_no | text unique | 자동생성 REQ-2026-0001 |
| type | enum(purchase, expense, trip, general) | |
| requester_id | FK→users | |
| department_id | FK→departments | |
| title | text | |
| description | text | |
| total_amount | money | 라인 합계 |
| status | enum(draft, submitted, approved, rejected, canceled) | |
| submitted_at / decided_at | timestamp | nullable |

### request_lines
| 컬럼 | 타입 | 비고 |
|---|---|---|
| request_id | FK→requests | |
| product_id | FK→products | nullable(자유서술 허용) |
| description | text | |
| qty | numeric | |
| estimated_unit_price | money | |
| amount | money | qty × price |

### approval_lines (결재선)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| request_id | FK→requests | |
| approver_id | FK→users | |
| step_no | int | 결재 순서 |
| status | enum(pending, approved, rejected, skipped) | |
| comment | text | |
| decided_at | timestamp | |

### approval_rules (결재규칙 — 결재선 자동구성)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| applies_to_type | enum(request type) | |
| min_amount / max_amount | money | 금액 구간 |
| routing | enum(org_chart, fixed_role, fixed_employee) | **라우팅 방식** |
| climb_levels | int | org_chart일 때: reports_to를 몇 단계 올라갈지 (예: 금액 클수록 더 높이) |
| fixed_role / fixed_employee_id | — | 고정 라우팅일 때 대상 |
| → 상신 시: 기안자 employee의 reports_to 체인을 따라 + 금액 구간 규칙으로 approval_lines 자동 생성 |
| → 기본은 **조직도 기반**(보고라인 따라 올라감), 금액 구간이 올라갈수록 더 상위까지 |

---

## C. 구매 (Purchase)

### purchase_orders
| 컬럼 | 타입 | 비고 |
|---|---|---|
| po_no | text unique | PO-2026-0001 |
| request_id | FK→requests | 출처(승인된 기안) |
| vendor_id | FK→vendors | |
| order_date / expected_date | date | |
| status | enum(open, partially_received, received, closed, canceled) | |
| subtotal / tax / total | money | sales/use tax |

### po_lines
| 컬럼 | 타입 | 비고 |
|---|---|---|
| po_id | FK→purchase_orders | |
| product_id | FK→products | |
| qty_ordered / qty_received | numeric | 부분입고 추적 |
| unit_price | money | |
| amount | money | |

---

## D. 재고 (Inventory) — 이동평균법

### inbounds (입고)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| inbound_no | text unique | |
| po_id | FK→purchase_orders | |
| received_date | date | |
| status | enum(draft, posted) | posted 시 재고·전표 반영 |

### inbound_lines
| 컬럼 | 타입 | 비고 |
|---|---|---|
| inbound_id | FK→inbounds | |
| po_line_id | FK→po_lines | |
| product_id | FK→products | |
| qty_received | numeric | |
| unit_cost | money | 입고 단가 |
| → **입고 분류는 product.type으로 자동 분기** (라인별): |
| · type=inventory → 판매재고로 입고 → (차) Inventory (대) GR/IR |
| · type=asset → 고정자산으로 입고 → FixedAsset 생성 + (차) Fixed Asset (대) GR/IR |
| · 한 입고서에 자산·재고 라인이 섞여도 각각 처리됨 |

### outbounds (출고) — 입고와 대칭
| 컬럼 | 타입 | 비고 |
|---|---|---|
| outbound_no | text unique | |
| type | enum(sale, consumption, disposal, transfer) | **용도 → 자동분개 분기** |
| issue_date | date | |
| ref_type / ref_id | text/int | 판매주문 등 출처(nullable) |
| memo | text | 사유 |
| status | enum(draft, posted) | posted 시 재고 차감·전표 |

### outbound_lines
| 컬럼 | 타입 | 비고 |
|---|---|---|
| outbound_id | FK→outbounds | |
| product_id | FK→products | |
| qty | numeric | |
| unit_cost | money | **출고시점 이동평균 단가**(stock_balances에서) |
| inventory_serial_id | FK→inventory_serials | 시리얼 품목이면 어떤 개체 |
| → 출고 유형별 자동분개: |
| · sale → (차) COGS(매출원가) (대) Inventory  *(매출인식은 §I AR invoice가 담당)* |
| · consumption → (차) 비용(부서/계정) (대) Inventory |
| · disposal → (차) 재고감모손실 (대) Inventory |
| · transfer → 위치 이동(회계 영향 없음, 다창고는 Phase 2+) |

### stock_movements (재고 이동 원장)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| product_id | FK→products | |
| movement_type | enum(inbound, outbound, adjustment) | |
| qty | numeric | 부호 또는 type로 방향 |
| unit_cost | money | |
| ref_type / ref_id | text/int | 출처 문서 추적 |
| moved_at | timestamp | |

### stock_balances (현재고)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| product_id | FK→products PK | 1품목 1행 |
| qty_on_hand | numeric | |
| avg_unit_cost | money | **이동평균** |
| total_value | money | qty × avg |
| → 입고 시: new_avg = (old_qty·old_avg + in_qty·in_cost)/(old_qty+in_qty) |

---

## E. 자산 (Fixed Asset) — 정액법

### fixed_assets
| 컬럼 | 타입 | 비고 |
|---|---|---|
| asset_no | text unique | |
| name | text | |
| model_name | text | 모델명 |
| serial_number | text | 시리얼번호 (자산 관리·추적) |
| source_inbound_line_id | FK→inbound_lines | 출처(nullable) |
| acquisition_cost | money | 취득원가 |
| acquisition_date | date | |
| useful_life_months | int | 내용연수 |
| salvage_value | money | 잔존가치 |
| accumulated_depreciation | money | 감가누계 |
| status | enum(in_use, disposed) | |
| asset_account_id / accum_account_id / expense_account_id | FK→accounts | 분개용 |

### depreciation_entries
| 컬럼 | 타입 | 비고 |
|---|---|---|
| asset_id | FK→fixed_assets | |
| period | text (YYYY-MM) | |
| amount | money | (취득-잔존)/내용연수 |
| journal_entry_id | FK→journal_entries | 자동분개 연결 |

---

## E-2. 재고 ↔ 자산 전환 (Reclassification)

판매재고와 고정자산을 양방향으로 전환. **장부가 기준으로 정확히 분개**한다.

### reclassifications
| 컬럼 | 타입 | 비고 |
|---|---|---|
| reclass_no | text unique | |
| type | enum(inventory_to_asset, asset_to_inventory) | 방향 |
| reclass_date | date | |
| product_id | FK→products | |
| qty | numeric | 보통 1 (시리얼 개체) |
| inventory_serial_id | FK→inventory_serials | 시리얼 품목이면 |
| fixed_asset_id | FK→fixed_assets | 생성되거나 전환되는 자산 |
| amount | money | 전환 기준액(아래) |
| journal_entry_id | FK→journal_entries | 자동분개 |
| memo | text | 사유 |

**전환 회계처리:**

```
① 재고 → 자산 (판매품을 회사가 직접 사용)
   기준액 = 출고시점 이동평균 단가
   재고 차감 + FixedAsset 생성(취득원가=기준액, 모델명/시리얼 승계)
   (차) Fixed Asset        (대) Inventory

② 자산 → 재고 (쓰던 자산을 판매하기로)
   기준액 = 장부가(NBV) = 취득원가 − 감가상각누계
   FixedAsset 상태=disposed, 재고에 NBV 단가로 입고(이동평균에 반영)
   (차) Inventory          (대) Fixed Asset (취득원가)
   (차) 감가상각누계        ↑ 누계 상계
```

> 시리얼 품목은 전환 시 동일 개체의 model_name/serial_number가 재고↔자산 사이에서 그대로 따라간다.

## F. 회계 (Accounting) — 복식부기

### journal_entries (전표)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| je_no | text unique | JE-2026-0001 |
| entry_date | date | |
| description | text | 적요 |
| source_type | enum(inbound, outbound, asset, reclass, ap_bill, payment, ar_invoice, receipt, expense, bank, depreciation, manual) | 자동/수동 출처 |
| source_id | int | 원천 문서 |
| status | enum(draft, posted, reversed) | |
| posted_at | timestamp | |
| reverses_id | FK→journal_entries | 이 전표가 역분개하는 원전표(nullable) |
| reversed_by_id | FK→journal_entries | 이 전표를 역분개한 전표(nullable) |
| → posted는 삭제·수정 불가, **역분개로만 정정**(POLICIES §G9). closed 기간 잠금 |

### journal_lines (분개)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| je_id | FK→journal_entries | |
| account_id | FK→accounts | |
| debit / credit | money | **불변식: Σ debit = Σ credit** |
| memo | text | |

### ap_bills (벤더 인보이스 = 미지급금) ← 3-way match의 중심
| 컬럼 | 타입 | 비고 |
|---|---|---|
| bill_no | text unique | 내부 채번 |
| vendor_invoice_no | text | 벤더가 준 인보이스 번호 |
| vendor_id | FK→vendors | |
| po_id | FK→purchase_orders | nullable |
| bill_date / due_date | date | payment_terms로 due 계산 |
| amount / balance | money | |
| match_status | enum(unmatched, matched, exception) | **PO↔입고↔인보이스 대조 결과** |
| source | enum(manual, ai_parsed) | AI가 PDF에서 생성했는지 |
| attachment_path | text | 인보이스 원본 PDF |
| status | enum(draft, open, partially_paid, paid) | |
| journal_entry_id | FK→journal_entries | |

### ap_bill_lines (인보이스 라인 ↔ 입고 라인 매칭)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| ap_bill_id | FK→ap_bills | |
| inbound_line_id | FK→inbound_lines | 매칭 대상(nullable) |
| description | text | |
| qty / unit_price / amount | numeric/money | |

### payments (지급) + payment_applications
| payments | vendor_id, payment_date, amount, method enum(check, ach, card, wire), bank_account_id |
| payment_applications | payment_id FK, ap_bill_id FK, applied_amount — 한 지급이 여러 청구에 배분 |

---

## G. 상태 전이 + 자동분개 (요약)

3-way match는 **GR/IR(Goods Received/Invoice Received) clearing 계정**으로 정확히 분개한다:

```
Request(draft)→submitted→[승인규칙으로 approval_lines 생성]
  → 모든 step approved → Request(approved) → PurchaseOrder(open) 자동생성

PO(open) → Inbound(posted)               ← ① 물건 받음 (Goods Received)
  → stock_movements(+), stock_balances 갱신(이동평균)
  → JournalEntry:  (차) Inventory       (대) GR/IR clearing
  → product.type=asset 이면 FixedAsset 생성 + (차) Fixed Asset (대) GR/IR

AP Bill(인보이스 수령, manual/AI) → PO·입고와 3-way match  ← ② 청구서 받음 (Invoice Received)
  → match_status = matched 시 posting
  → JournalEntry:  (차) GR/IR clearing  (대) AP   (+ 차액 있으면 차이계정)

Payment(posted) → payment_applications → AP Bill 잔액 차감   ← ③ 지급
  → JournalEntry:  (차) AP   (대) Cash

Outbound(posted) → stock_movements(−), stock_balances 차감(이동평균 단가로)
  → JournalEntry(유형별):  (차) COGS/비용/감모손실   (대) Inventory

Reclassification(posted) → 재고↔자산 전환
  → inv→asset: (차) Fixed Asset (대) Inventory
  → asset→inv: (차) Inventory + (차) 감가누계 (대) Fixed Asset

월말 Depreciation run → depreciation_entries
  → JournalEntry:  (차) Depreciation Expense   (대) Accumulated Depreciation

── 매출(AR) 측 ──────────────────────────────
SO(open) → Outbound(sale, posted)        ← 물건 나감
  → (차) COGS (대) Inventory  (원가 측)
AR Invoice(posted) → 고객 청구           ← 매출 인식
  → (차) AR (대) Revenue (+ 대) Sales Tax Payable
Receipt(posted) → receipt_applications   ← 수금
  → (차) Bank/Cash (대) AR

── 경비/정산 측 ─────────────────────────────
Expense Request(approved) → 직원 환급채무
  → (차) 비용(카테고리별 계정) (대) Employee Payable
Reimbursement Payment(posted)
  → (차) Employee Payable (대) Cash

── 은행 대사 ────────────────────────────────
Bank Statement 업로드 → AI 적요 추출 → statement_lines
  → 기존 전표와 자동 매칭(지급/수금)
  → 미매칭분(은행수수료·이자 등)은 새 JE 생성: (차/대) 해당계정 (대/차) Bank
```

> GR/IR clearing이 입고 시점과 인보이스 시점의 **시차를 흡수**한다. 둘 다 처리되면 GR/IR 잔액=0. 미결제/미입고가 잔액으로 남아 추적됨.

---

## H. 회계기간 & 리포트 (QuickBooks 대체용)

### accounting_periods (회계기간 / 마감)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| period | text (YYYY-MM) | 월 단위 |
| status | enum(open, closed) | **마감되면 해당 기간 전표 수정 잠금** |
| closed_at / closed_by | timestamp/FK | |
| → "1월 마감" = 1월 period를 closed로. 이후 전표는 후속 기간으로만 |

### 리포트 (별도 테이블 아님 — 전표에서 산출되는 "도구")
복식부기 전표(journal_lines)에서 동적 생성. **사람=메뉴, AI=대화**로 같은 함수 호출:
- **Balance Sheet (BS)** — 재무상태표
- **Income Statement (IS / P&L)** — 손익계산서
- **Cash Flow (CF)** — 현금흐름표
- **Trial Balance (TB)** — 시산표
- **General Ledger detail** — 계정별 원장
- **AP Aging** — 미지급금 연령표
- **Inventory valuation** — 재고 평가
- 예) AI: *"1월 마감자료 줘"* → `generate_financials(period='2026-01')` 호출 → BS+IS 반환

## I. 매출 / AR (Sales) — 매입측의 거울구조

### customers (고객) — vendors의 대칭
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name / customer_no | text | |
| billing_address / contact | text | |
| payment_terms | text | net30 등 |
| ar_account_id | FK→accounts | 기본 AR 계정 |

### sales_orders (수주, SO) + so_lines — purchase_orders의 대칭
| sales_orders | so_no, customer_id, order_date, status enum(draft, approved, open, shipped, invoiced, closed) |
| so_lines | so_id, product_id, qty_ordered/qty_shipped, unit_price, amount |
> 출고(Outbound type=sale)가 SO를 ref로 연결 → 원가(COGS) 측 분개.

### ar_invoices (고객 인보이스 = 미수금) + ar_invoice_lines — ap_bills의 대칭
| 컬럼 | 타입 | 비고 |
|---|---|---|
| invoice_no | text unique | |
| customer_id | FK→customers | |
| so_id | FK→sales_orders | nullable |
| invoice_date / due_date | date | |
| subtotal / tax_amount / total / balance | money | |
| tax_code_id | FK→tax_codes | **sales tax** |
| status | enum(draft, open, partially_paid, paid) | |
| journal_entry_id | FK→journal_entries | (차)AR (대)Revenue+(대)Sales Tax Payable |
| ar_invoice_lines | ar_invoice_id, product_id, description, qty, unit_price, amount |

### receipts (수금) + receipt_applications — payments의 대칭
| receipts | customer_id, receipt_date, amount, method, bank_account_id |
| receipt_applications | receipt_id FK, ar_invoice_id FK, applied_amount — 한 수금이 여러 인보이스에 배분 |
> (차) Bank/Cash (대) AR. **AR Aging** 리포트는 ar_invoices.balance + due_date에서 산출.

---

## J. 은행 / 현금 (Bank) — 월간 Statement 업로드 대사

> 라이브 뱅크피드 ❌(완전 로컬). **월간 statement 업로드 → AI가 적요 추출 → 기존 전표와 대사.**
>
> **왜 업로드 방식인가:** QB식 실시간 연동은 은행 직접 API가 아니라 **애그리게이터(Plaid/Yodlee/MX) = 클라우드 중개**를 거친다 → 은행 자격증명을 제3자에 넘겨야 함 → "데이터 비유출" 셀링포인트와 충돌. 업로드 방식은 **은행 무관 + 완전 로컬**이라 이 제품엔 오히려 정답. (OFX/QFX/CSV 파일도 지원. Plaid는 옵션형 클라우드 애드온으로만.)

### bank_accounts
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name | text | "Chase 운영계좌" |
| account_no_masked | text | |
| gl_account_id | FK→accounts | 연결된 현금 GL 계정 |
| currency | text | USD |

### bank_statements (업로드 단위)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| bank_account_id | FK→bank_accounts | |
| period | text (YYYY-MM) | |
| opening_balance / closing_balance | money | 대사 검증용 |
| source_file_path | text | 업로드 원본(PDF/CSV) |
| status | enum(uploaded, parsed, reconciled) | |

### bank_statement_lines (AI가 적요 추출)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| statement_id | FK→bank_statements | |
| txn_date | date | |
| description | text | **적요(AI 파싱)** |
| amount | money | +입금/−출금 |
| matched_journal_line_id | FK→journal_lines | 매칭된 전표(nullable) |
| match_status | enum(unmatched, matched, new_je) | |
| → unmatched: AI가 후보 제시 또는 신규 JE(수수료·이자 등) 생성 제안 |

---

## K. 경비 / 정산 (Expense) — Non-PO 지출·직원 환급

> ★ 출장 신청 등 **PO 없는 지출**의 종착점. 결재 승인 → 직원 환급채무 → 지급.
>
> ⚠️ **정합성 결정(정합성점검):** 경비도 **§B `requests` 워크플로우를 재사용**한다(`requests.type=expense/trip` + `approval_lines`로 결재). 따로 `approvals` 테이블·별도 결재엔진 만들지 않음. 아래 `expense_requests`는 **`requests`의 *경비 특화 확장*** (1:1 연결)으로, 환급대상·정산상태·전표 등 경비 고유 속성만 담는다.

### expense_requests (requests의 경비 확장 — 1:1)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| request_id | FK→requests (unique) | **§B 기안/결재 워크플로우 재사용** (별도 approvals 테이블 ❌) |
| employee_id | FK→employees | 신청자(=환급 대상) |
| expense_type | enum(travel, reimbursement, advance) | |
| status | enum(draft, submitted, approved, rejected, reimbursed) | requests.status와 동기 + reimbursed 단계 |
| journal_entry_id | FK→journal_entries | 승인 시 (차)비용 (대)Employee Payable |
| → 결재선·금액·제목은 requests/request_lines/approval_lines에서, 경비 고유속성만 여기 |

### expense_lines
| 컬럼 | 타입 | 비고 |
|---|---|---|
| expense_request_id | FK→expense_requests | |
| expense_date | date | |
| category_id | FK→expense_categories | → posting 규칙으로 비용계정 매핑 |
| description | text | |
| amount | money | |
| attachment_path | text | 영수증(AI 파싱 가능) |

> 환급 지급은 §F payments 재사용(payee=employee). (차) Employee Payable (대) Cash.
> 사전신청(출장 전 예상액)과 정산(실제 영수증)은 같은 테이블에서 status로 구분.

---

## K2. 문서 수신·분류 (RAG·보안의 핵심축 — DESIGN §8.4)

### documents (모든 수신 파일의 단일 레지스트리)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| file_path | text | 원본 저장 경로 |
| filename / mime | text | |
| category_id | FK→document_categories | **AI 분류** (인보이스/명세서/영수증/계약/급여…) |
| acl_scope | enum(hr, finance, inventory, …, general) | **ACL 도메인** (DESIGN §8.5 ①) |
| acl_level | int (1~3) | **ACL 등급** (②). 예 급여=(hr,3) → 검색게이트 필터 |
| subject_employee_id | FK→employees | 대상 직원(③ 경계 판정용, nullable) |
| extracted_text | text | OCR/추출 (RAG 색인 원천) |
| linked_type / linked_id | text/int | 연결 엔티티(벤더·고객·직원·기간 등) |
| classified_by | enum(ai, human) | |
| confidence | numeric | 낮으면 ④게이팅(되묻기) |
| status | enum(quarantined, classified, needs_review, routed, rejected) | **격리→승급 흐름** |
| is_indexed | bool | **기본 false. 승급된 정식 레코드만 RAG 색인**(Default-Not-Indexed, §8.6) |
| relevance | enum(business, uncategorized) | 업무 카테고리 매핑 실패=uncategorized→색인·라우팅 ❌ |
| → **Default-Deny: 민감도 불확실 시 가장 제한적 등급으로 시작**, 사람 확인 후 완화 |
| → §8.6 입력 관문: 분류·검증 통과 전엔 라이브/RAG 진입 불가. 무관/무응답 → purge |

### document_categories (설정형 — admin이 카테고리·규칙 관리)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| name | text | invoice/bank_statement/receipt/contract/payroll… |
| default_sensitivity | enum | 이 카테고리의 기본 ACL |
| route_to | text | 트리거할 워크플로우(ap_draft/reconcile/expense…) |
| requires_human_review | bool | 급여·계약 등 true |

### document_chunks (RAG 벡터 색인 — pgvector)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| document_id | FK→documents | |
| chunk_text | text | |
| embedding | vector | pgvector |
| acl_scope / acl_level / subject_employee_id | — | **문서 ACL 복제 → 검색 쿼리서 강제 필터(검색 전 거르기)** |
| → RAG 검색: `WHERE user.level[acl_scope] ≥ acl_level AND subject ∈ user.boundary` 강제 |

## L. 온보딩 / 마이그레이션 (상용 판매용 — go-to-market 마일스톤)

> 본인 용도는 0에서 시작이라 불필요. **기존 시스템(QB 등)을 쓰던 고객에 판매할 때** 필요한 이행 기능.

**구성:**
1. **마스터 데이터 임포트** — customers/vendors/products/COA를 CSV·Excel·QB 익스포트에서. **AI가 컬럼·계정 매핑 보조**.
2. **기초잔액(cutover)** — 전환일 기준 시산표를 **Opening Balance Equity** 계정 상대로 한 전표로 입력. (회계 정석: 이후 잔액 0 검증)
3. **미결 거래 시드** — 미지급 ap_bills / 미수 ar_invoices / stock_balances 현재고 / fixed_assets(+감가누계)를 as-of 잔액으로. → aging·재무제표 즉시 정합.
4. **검증 리포트** — 이행 후 시산표가 원본과 일치하는지 자동 대조.

> 별도 신규 테이블 최소화 — 기존 service API/posting을 재사용해 "import = 평소 거래를 일괄 생성"으로 구현. **Opening Balance Equity** 계정만 COA 시드에 추가.

## 확정된 모델링 (Q1·Q3·Q5)
- **✅ Q1: 입고를 별도 문서(Inbound)로.** 부분입고·검수·정식회계 지원.
- **✅ Q3: 3-way match (PO↔입고↔벤더인보이스).** AP는 인보이스 수령 시 생성(manual/AI). GR/IR clearing 사용.
- **✅ Q5: QuickBooks 미국 소기업 기본 COA를 시드.** **🎯 전략 목표: 이 시스템이 궁극적으로 QuickBooks를 대체** → 회계 모듈은 완전한 장부(GL/AP/AR/재무제표/뱅크릴레/1099)로 키운다.

## 확정 (Q2·Q4·Q6)
- **✅ Q2: 조직도 기반 라우팅이 기본**, 예외는 **admin 권한자가 그때그때 셋팅**(approval_rules에 fixed_role/fixed_employee 라우팅).
- **✅ Q4: USD 단일 통화.** 다중통화 안 함.
- **✅ Q6: 재무제표/리포트 필요** (BS/IS/CF/TB/GL detail/AP aging/재고평가). 전표에서 동적 산출, **AI가 대화로 호출 가능**(예: "1월 마감자료"). 회계기간(마감) 개념 포함.
