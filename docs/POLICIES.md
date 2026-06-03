# 001 — 전역 정책 (C그룹 G9~G13) — 확정

작지만 시스템 전반에 적용되는 규칙들. 합리적 기본값으로 확정.

---

## G9. 전기된 전표 수정 정책 — 역분개 only (감사 무결성)

- **posted 전표는 삭제·수정 불가.** 정정은 **역분개(reversing entry)** 로만.
  - `journal_entries`에 `reverses_id`(원전표) / `reversed_by_id`(역분개) 추가.
  - 역분개 = 원전표의 차/대를 반대로 한 새 전표 + 필요 시 올바른 전표 재작성.
- **마감(closed) 기간**에는 어떤 전표도 못 들어감 → 후속 open 기간에 조정분개.
- 모든 변경은 `audit_logs`에 기록(누가·언제·무엇·근거). **AI가 만든 전표도 동일 규칙.**
- draft 상태는 자유롭게 수정·삭제 가능(아직 장부 아님).

## G10. 문서 채번 — 유형별 순번, gapless

- 형식: `PREFIX-YYYY-NNNN` (예: `PO-2026-0001`, `JE-2026-0042`, `EXP-2026-0007`).
- **유형별·연도별** 카운터, 연초 리셋.
- **gapless(빈번호 없음)** — 감사 요건. 번호는 **커밋 트랜잭션 안에서 할당**(롤백 시 번호도 롤백).
- 전용 테이블 `doc_sequences(doc_type, year, last_no)` + row lock으로 동시성 보장.
- 접두어: PO, INB(입고), OUT(출고), JE(전표), BILL(AP), PAY(지급), SO(수주), INV(AR인보이스), RCT(수금), EXP(경비), RCL(전환), DEP(감가).

## G11. 권한 매트릭스 — 역할 기반 + 모듈 수준

> ⚠️ **정합성 노트:** 아래 4역할 매트릭스는 **각 역할의 "기본 scope 묶음"** 을 보여주는 *요약*이다. **정본 권한 모델은 DESIGN §8.5의 3축(scope×level×data_boundary)**. 선형 4역할만으로는 "accountant가 HR 연봉을 보나?"(재무≠인사)를 표현 못 함 → 그래서 §8.5가 권위. 이 표는 출고 시 역할별 기본값으로 사용.

역할(`users.role`)을 4단계로 확장: **employee / manager / accountant / admin.**

| 기능 | employee | manager | accountant | admin |
|---|:--:|:--:|:--:|:--:|
| 본인 기안·경비 신청, 본인 문서 조회 | ✅ | ✅ | ✅ | ✅ |
| 자신에게 라우팅된 결재 승인/반려 | — | ✅ | ✅ | ✅ |
| 재고·구매·자산 운영(입출고·PO 등) | 일부 | ✅ | ✅ | ✅ |
| **전표·원장·재무제표(GL) 조회** | ❌ | ❌ | ✅ | ✅ |
| AP/AR·지급·수금·은행대사 | ❌ | ❌ | ✅ | ✅ |
| 기간 마감 / 역분개 | ❌ | ❌ | ✅ | ✅ |
| 사용자·역할·**posting 규칙·시스템 설정** | ❌ | ❌ | ❌ | ✅ |

- 핵심: **경비 신청자(employee)는 GL/재무제표를 못 본다.** 회계 가시성은 accountant 이상.
- **AI 도구도 호출자의 권한을 상속** — 사용자가 못 하는 걸 AI에게 시켜도 못 함.

## G12. 알림 — in-app 알림센터 + SSE 실시간 (이메일은 옵션)

- 완전 로컬이므로 **in-app 알림이 기본**. `notifications` 테이블 + **SSE로 실시간 푸시**.
- 트리거: 결재 도착/승인/반려, 본인 기안 상태변경, AI의 추가질문(불확실성 게이팅), 은행대사 필요, AP/AR 만기 임박.
- 이메일/슬랙은 **옵션 어댑터**(고객이 SMTP 설정 시) — 기본 off.

## G13. 백업 / 복구 — 어플라이언스 자동 백업

- **DB**: APScheduler로 **야간 자동 `pg_dump`** → 로컬 디스크(+가능 시 별도 디스크/NAS).
- **첨부파일**: `uploads/`(인보이스·영수증·명세서 원본) 동기 백업.
- **보존**: 일 7 / 주 4 / 월 12 회전(rolling). 
- **복구**: 관리자 화면에서 백업 선택 → 원클릭 복원(DB+파일 함께).
- **무결성**: 백업 후 자동 검증(복원 테스트 or 체크섬). 
- 단일테넌트라 각 어플라이언스가 자기 백업을 소유 → 고객 데이터 격리 자연 보장.

---

## 신규/변경 테이블 요약 (이 정책으로)

- `journal_entries` += `reverses_id`, `reversed_by_id`
- `users.role` enum → **employee, manager, accountant, admin**
- 신규 `doc_sequences(doc_type, year, last_no)`
- 신규 `notifications(user_id, type, title, body, link, is_read, created_at)`
- 신규 `audit_logs(actor_user_id, action, entity_type, entity_id, detail_json, at)` — AI/사람 공통
