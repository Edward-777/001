# 001 ERP — Phase 1 코드 리뷰 (M0–M15)

> 리뷰 대상: Phase 1 전체 (15개 모듈, ~4,929 LOC, 100 tests green, ruff clean).
> 목적: 코더 핸드오프. 우선순위(P0/P1/P2)별로 `파일:라인 · 이슈 · 왜 · 수정방향`.
> 원칙: **"동작한다"가 아니라 "믿을 수 있다"** 기준. 회계·권한은 정확성/통제가 곧 제품.

---

## 0. 총평

백엔드 아키텍처는 최상급이다. 이벤트 디커플링(회계가 도메인을 모름), posting 단일 관문, 역분개 재귀, 모듈 경계 — 규율이 일관된다. **가장 큰 리스크는 새 코드가 아니라 "완성됐는데 연결 안 된 것"(권한 게이트)과 "검증이 빠진 통제"(은행/보조원장)다.** 아래 P0를 닫기 전엔 Phase 2(AI)를 올리면 안 된다.

---

## 0.5 우리 측 검증 (intent 확인, 2026-06-03)

리뷰어가 **우리 설계 의도를 오해했는지** 코드 대조로 전수 검증함. **결론: 오해 없음.** 거의 모든 지적이 코드로 재현됨. 아래는 항목별 판정 + 대응 방침.

| 항목 | 판정 | 우리 메모 |
|---|---|---|
| P0-1 권한게이트 미연결 | ✅ **확인** | `require_access`가 **어느 라우트·서비스에서도 호출 안 됨**(grep 확인). authz 전체가 테스트만 있고 미사용. **최우선 수용.** |
| P0-2 채번 race | ✅ **확인** | `sequences.py:36` None분기 — Postgres 연초 동시 INSERT시 unique 충돌 실재. SQLite(dev)는 글로벌락이라 안 터짐 → prod 한정. 수용. |
| P0-3 은행 잔액검증 | ✅ 타당 | M12 의도는 "라인 매칭"이었음. opening+Σ==closing 검증은 **정당한 강화**(누락거래 적발). 수용. |
| P0-4 보조원장↔GL 대조 | ✅ 타당, ⚠️ 우선순위 P1급 | GL·aging **각각은 정확**. 둘의 cross-check가 없을 뿐(버그 아닌 추가통제). 수용하되 P1로 강등. |
| P0-5 기본 secret/cookie | ✅ **확인** | 부팅 가드 없음. 수용. |
| P1-1 schemas.py 부재 | ✅ **확인** | **우리 ARCHITECTURE §2가 schemas.py를 명시했는데 미구현** → 의도와 구현 괴리(`approval→auth.models.User` 직접쿼리 등 4건). 정당한 지적. 수용. |
| **P1-2 회계가 inv/sales 읽음** | ⚠️ **intent 명확화 (오해 아님)** | "회계는 재고를 모른다"는 **posting(자동분개) 한정** 원칙. AP매칭·리포트의 **read-query는 의도적 허용**(M10 커밋에 기록). 리뷰어도 "문서 명시" 옵션 제시함. **결정: 의도를 문서에 명문화**, `reporting` 모듈 분리는 선택. |
| P1-3 CF 누락 | ✅ 타당 | M13가 CF를 주장했으나 미구현(정직성 갭). 수용 — CF 추가 or "미구현" 명시. |
| P1-4 reports_to 미검증 | ✅ **확인** | read쪽 cycle guard만 있고 write 검증 없음. 잘못된 보고선=권한누수. 수용. |
| P1-5 Alembic 미구성 | ✅ 사실 | create_all만. 수용(베이스라인 생성). |
| P1-6 은행매칭 금액only | ✅ 사실 | 우리도 인지(M12 단순화). 날짜창 추가 수용. |
| P1-7 백업 G13 미달 | ✅ 사실 | 특히 **pg_dump URL 비번 노출**은 실보안 nit. 수용. |
| P1-8 기말마감 분개 | ✅ intent=잠정BS | 즉석 net income은 의도적(중간결산). "연도 클로징 미구현" 문서화로 수용. |
| P2 전반 (DRY/nit) | ✅ **정확** | `Money=Numeric` ~10중복, `_CENTS` ~8곳, aging 복붙, `grant_scope` add+append 중복(`service.py:57-58` 확인) 등 전부 실재. 수용. |

**총괄:** 15개 영역 중 **fundamental 오해 0건.** P1-2 한 건만 "read-dependency는 의도였다"는 명확화가 필요하고, 이마저 리뷰어가 이미 hedge함. → 리뷰 신뢰. P0부터 순서대로 처리.

### 처리 현황 (2026-06-03, 107 tests green)

| 묶음 | 커밋 | 상태 |
|---|---|---|
| **P0 전부** (1–5) | `6b67b68` | ✅ 완료 (권한게이트 연결+역할기본scope, 채번race savepoint, 은행잔액검증, 보조원장↔GL, 부팅가드, +timing/grant_scope) |
| **P1 전부** (1–8) | `0d50c54`, `f89d543` | ✅ 완료 (캡슐화/auth.service 계약타입, read-dep 문서화, **현금흐름표**, reports_to 검증, **Alembic 베이스라인**, 날짜윈도우, **백업 강화**, 마감 문서화) |
| **P2 핵심** | `f89d543` | ✅ Money/Qty 공용화(9파일), events `.get`, notify 벌크update, FIXED_ROLE 결정적, 더미해시 |
| P2 잔여 (저위험 cosmetic) | — | ◻ `_CENTS`/`current_year` 전면 치환, aging/line-sum 헬퍼화, classify 파라미터(→Phase3), UserScope CheckConstraint, httpx 핀 등. **동작 무관**, 점진 정리 |

→ **P0+P1 = "믿을 수 있는 회계 엔진" 달성.** Phase 2(AI) 진입 안전.

---

## P0 — Phase 2 전 필수 (보안 / 정합성)

| # | 파일:라인 | 이슈 | 왜 | 수정 방향 |
|---|---|---|---|---|
| P0-1 | `app/web/main_routes.py:132` (전 라우트) | **권한 게이트가 라우트에 미연결.** `_guard`는 인증(로그인)만, 인가(scope×level) 없음. financials를 로그인한 누구나 조회 | 헤드라인 보안속성("못 볼 건 못 본다")이 실제 문에서 무효. 권한시스템은 완성됐는데 미사용 | `require_user` 의존성에 `auth.require_access(grants, scope, level)` 통합. financials=(finance,3), approvals=해당 scope 등 |
| P0-2 | `app/core/sequences.py:30-41` | gapless 채번이 **연도 첫 번호**에서 동시성 race (둘 다 INSERT→`uq_doc_seq` IntegrityError) | "gapless 감사" 셀링포인트. 30 동시사용자에서 연초 첫 PO/JE 실패 가능 | `INSERT ... ON CONFLICT DO NOTHING` 후 재조회, 또는 연도롤오버시 시퀀스 행 선생성, 또는 IntegrityError 1회 재시도 |
| P0-3 | `app/modules/bank/service.py:82-111` | 은행대사가 **opening + Σlines == closing 검증 안 함**. `_refresh_status`는 "전 라인 매칭"만 봄 | 은행대사의 존재이유=누락거래 적발. 잔액검증 없으면 못 잡음 | `reconcile` 말미에 `opening + Σamount == closing` assert, 불일치시 상태=exception |
| P0-4 | `app/modules/accounting/reports.py:164-191` | **보조원장 ↔ 통제계정 정합성 미검증.** `ap_aging.total`이 GL의 AP 계정 잔액과 같은지 대조 안 함 | 둘이 어긋나면(반올림/수동전표) 재무제표 AP ≠ aging AP인데 시스템이 모름. 회계사 1차 의심지점 | aging 산출시 GL 통제계정 잔액과 비교하는 검증 리포트/assert 추가 |
| P0-5 | `app/core/config.py:13` + `app/main.py:28` | prod 기본 `secret_key="dev-secret-change-me"` + `secure_cookies=False` 가드 없음 | 기본값으로 출고시 세션쿠키 위조 가능 | 부팅시 `secure_cookies and secret==default` → 거부/경고 |

---

## P1 — 곧 (정합성 완성 / 누적되는 구조 부채)

| # | 파일:라인 | 이슈 | 수정 방향 |
|---|---|---|---|
| P1-1 | 전 모듈 (`schemas.py` 부재) | 공개 계약 타입이 `models.py`에만 있어 **남의 models 직접 import 4건**: `expense→approval.models.RequestType`, `approval→auth.models.User`(테이블 직접 쿼리, `service.py:17,112`), `hr→auth.models.DataBoundary`, `hr→auth.permissions.BoundaryResolver`. web까지 번짐(`main_routes.py:15`, `deps.py:11`) | 각 모듈에 `schemas.py` 신설 → enum/DTO 이전, 남들은 거기서만 import. `auth.service.get_user()`·`find_users_by_role()` 추가. **라인 `list[dict]`도 DTO로 승격(AI 도구 자동생성 복구)** |
| P1-2 | `accounting/ap.py:16`, `accounting/reports.py:179,195` | 의존 방향 모순: 회계(AP·reports)가 inventory·sales를 직접 읽음 (§3 "회계는 재고를 모른다"와 충돌) | **reports를 별도 `reporting` 모듈로 분리**(횡단=맨 위에서 모두 읽기). AP→inventory는 "AP는 GR을 query"로 문서에 명시하거나 read-port로 분리 |
| P1-3 | `accounting/reports.py` | **현금흐름표(CF) 누락** → M13 "완료" 미달. `generate_financials`도 IS+BS만 | 간접법 CF(BS 2시점 차 + 조정) 추가, `generate_financials`에 TB/CF 포함 |
| P1-4 | `hr/service.py:34` (`create_employee`) | `reports_to_id` 순환/자기참조/존재 미검증. 잘못된 보고선=권한 누수 | 쓰기시 self-ref 차단 + 순환 검사(또는 최소 FK존재 확인) |
| P1-5 | `app/main.py:36` | Alembic 참조만, 실제 미구성. 유일 스키마 경로=`create_all` | 베이스라인 마이그레이션 생성(스키마 커지기 전이 가장 쌈) |
| P1-6 | `accounting/service.py:41` + `bank/service.py:98` | 은행 매칭이 **금액 일치 only + `.first()`**. 날짜창·상대 없음 → 오매칭 | 날짜 근접 윈도우 추가, 후보 다수시 명시 처리 |
| P1-7 | `app/core/backup.py` | POLICIES §G13 미달: tiered 회전(일7/주4/월12) 없음(flat keep=7), `uploads/` 백업 없음, 무결성 검증 없음, pg_dump URL로 비번 ps 노출 | 회전 정책 구현, uploads 동기백업, 백업후 검증, `PGPASSWORD`/`.pgpass` |
| P1-8 | `accounting/reports.py:99-113` | 기말 마감분개(net income→Retained Earnings) 없음. equity에 즉석 가산 | 잠정 BS로는 OK — **"연도 클로징 미구현"을 문서에 명시**하거나 close 분개 추가 |

---

## P2 — 정리 / 중복 제거 / 단순화 (대량·저위험)

### 중복 (core로 통합)
- **`Money=Numeric(15,2)` / `Qty=Numeric(15,3)` ~10개 파일 재정의** → `core`로. (ledger/ap/inventory/sales/assets/procurement/expense/approval/bank/models)
- **`_CENTS=Decimal("0.01")` ~8곳 + `_ZERO=Decimal("0.00")`(reports) + 인라인(approval:66)** → `core.money` 통합.
- **`Decimal(str(x))` 변환 의식 전역** → `money(x)` 헬퍼 하나로 (`posting._d`를 core로 승격).
- **`_year()`/`_now_year()`/인라인 `datetime.now(...).year`** → `core.current_year()`.

### 중복 (헬퍼화)
- **라인합산 패턴 6곳** (`ap.py:63`, `sales:73,111`, `procurement:65`, `approval:62`) → `compute_lines(raw)→(rows, subtotal)`.
- **비용계정 그룹핑 2곳** (`accounting/handlers.py:85` consumption, `:181` expense) → `debit_by_account(lines, credit_role)`.
- **aging 2함수 거의 복붙** (`reports.py:164` ap, `:178` ar) → `_aging(items, due_of, bal_of, row_of)`.
- **IS/BS net income 계산 중복** (`reports.py:90,104`) → `_net_income(groups)`.
- **notify 블록 2회 복붙** (`approval/service.py:146,188`) → `_notify_pending(session, req, approver_id)`.
- **`_guard(user)` 보일러플레이트 8곳+** → `require_user` 의존성(P0-1과 통합).
- **`mark_all_read` N행 로드 후 루프** (`notifications/service.py:51`) → 벌크 `update(...).values(is_read=True)`.

### 복잡도 / 일관성 nit
- `accounting` 내부 순환 냄새: 바닥 import(`service.py:85,121` `# noqa: E402`) + 함수내 import(`posting.py:157`, `bank/service.py:143`) → `accounts.py`(role↔account) 분리로 해소.
- 함수내 `from datetime import ...` (`posting.py:74,107`) → 상단으로.
- `assets/service.py:34` `_period_date`가 day=28 하드코딩 → `calendar.monthrange`로 월말, 또는 주석.
- Outbound가 `InboundStatus` 차용 (`inventory/service.py:250,268,290`, `models.py:110`) → 공용 `DocStatus{DRAFT,POSTED}`.
- `sales/service.py:100` 지역변수 `inv = ARInvoice(...)` → `invoice` (코드베이스 관습 `inv`=inventory와 충돌).
- `get_account_by_role(...).id` None 미체크 다수(handlers) → `_role_id()` 래퍼(없으면 PostingError).
- `documents/service.py:35` `classify()` 11파라미터 → Phase3에서 분류결과 객체로.
- `documents/models.py:52` `extracted_text` 무제한 `String` (의도 OK, 일관성 메모).
- `auth/service.py:34` `authenticate` 타이밍 사이드채널(미존재 이메일 즉시 반환) → 더미 해시 verify.
- `auth/service.py:54` `grant_scope` `session.add`+`append` 중복.
- `core/events.py:49` `defaultdict` 키 누적 → `.get(type, ())`.
- `auth/models.py:68` `UserScope.level` DB CheckConstraint(1~3) 없음.
- `approval/service.py:115` FIXED_ROLE `users[:1]` 비결정적(주석).
- pytest 경고: starlette TestClient httpx deprecation(`testpaths` 무해, 추후 httpx 핀).

---

## 절대 건드리지 말 것 (검증된 강점)

- **posting 엔진**(`posting.py:85`): balanced 체크 → 기간게이트 → 채번 → 감사로그 → 역분개가 한 함수에 응축. 단일 책임의 밀도. 추상화 추가 금지.
- **이벤트 디커플링**: inventory/sales/assets가 GL 계정을 1도 모름. `accounting/handlers.py`만 분개. 모범.
- **역분개 netting** (`reports.py:22` `_POSTED=["posted","reversed"]`): 상계되게 둘 다 포함 — 회계 정확.
- **BS/TB `balanced` 자가검증** (`reports.py:68,112`): 런타임 불변식 검사.
- **이동평균**: 출고시 평균 불변, 수량/가치만 감소 (`inventory/service.py:193`). 정확.
- **멱등 감가** (`assets/service.py:97`): (asset,period) 중복 방지, cost-salvage 상한.
- **routes 얇음**(`web/main_routes.py`): guard→service→template, 비즈로직 0.
- **backup/scheduler 분리**: 동기·테스트가능 + 기본 off + 지연 import.
- **documents Default-Deny** (`documents/service.py:12`): 격리·미색인 시작.

---

## 권장 작업 순서

1. **P0-1 권한 게이트 연결** (+`require_user` 의존성, P2 `_guard` 정리 동반) — 보안.
2. **P0-2~4 정합성 통제** (채번 race, 은행 잔액검증, 보조원장↔GL) — 신뢰.
3. **P1-1 schemas.py** — 모듈화 완성 + P1 라인 DTO + AI 도구 준비를 한 번에.
4. **P2 core 통합**(Money/_CENTS/money/year) — LOC 대폭 감소, 이후 작업 가벼워짐.
5. P1-2 reporting 분리, P1-3 CF, 나머지 P1.
6. P2 나머지 nit.

> P0+P1 마무리 = "믿을 수 있는 회계 엔진". 그 위에 Phase 2(AI 도구·권한상속·RAG)를 올리는 게 안전한 순서.
