# 001 — 마스터 요약 (한 장)

> 프로젝트 **001** 설계의 전체 그림. 상세는 5개 문서로. (2026-06-03 정합성 점검 완료)
> 📂 [DESIGN.md](DESIGN.md) · [docs/SCHEMA.md](docs/SCHEMA.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/POLICIES.md](docs/POLICIES.md) · [docs/AI-AGENT.md](docs/AI-AGENT.md)

---

## 한 문장
**1인~30명 소규모 기업용, 완전 로컬에서 AI가 직접 운전하는 경량 ERP.** 자사 서버 하드웨어에 묶어 파는 단일테넌트 어플라이언스. 경쟁자 = QuickBooks(우리는 더 쉽고·가볍고·재고/자산/SCM까지 강함).

## 비전 / 사업
- **엔드게임:** 대화만으로 회사 전체 운영. ("출장 가" → AI가 기안·결재·전표까지)
- **사업모델:** 상용 제품, 서버에 번들. 고객마다 자기 박스(데이터 비유출 = **셀링포인트**). SaaS 멀티테넌트 ❌.
- **완전 로컬:** 데이터·AI 모두 고객 박스 안. "로컬"=데이터 비유출이지 기기제한 아님 → 폰/태블릿은 LAN/VPN 브라우저로 접속(PWA, 네이티브앱 불필요).

## 플랫폼 / 스택
- 동시 30명 · 호스트1대(GPU)+브라우저 · 내부망+VPN(WireGuard) · HTTPS/원격2FA
- **Python·FastAPI·PostgreSQL·SQLAlchemy·HTMX/Jinja2/Tailwind·세션인증·APScheduler·Ollama·pgvector**
- ❌ Redis·Celery·Nginx·Docker·기존코드재활용·데이터마이그레이션(본인용)

## 업무 도메인 (Phase 1 = 전 회계 사이클)
```
기안 → [조직도 기반 결재] → 구매(PO) → 입고(별도문서) → 재고(이동평균) ⇄ 자산(정액감가)
                                                    └ 모델명·시리얼# 추적
        + 매출/AR(고객·수주·인보이스·수금)  + 경비정산(Non-PO·직원환급)  + 은행대사(월간 statement 업로드+AI)
        → 모든 단계 자동 복식부기 분개 → 회계기간(마감) → 재무제표(BS/IS/CF/TB/AP·AR aging)
```
- **회계:** US GAAP·USD·sales tax·QuickBooks식 COA. AP=**3-way match**(PO↔입고↔인보이스, GR/IR clearing).
- **HR/조직도:** employees+`reports_to` → 결재선·권한경계의 토대.
- **재고↔자산 양방향 전환**(reclassification, 장부가 분개).

## 아키텍처
- **모듈러 모놀리스**(단일프로세스, 엄격분리). 모듈: core·auth·hr·approval·procurement·inventory·assets·sales·expense·bank·accounting·documents·ai.
- **모듈 유일 진입점 = `service.py`** (사람 UI·AI 도구·타모듈이 같은 함수 호출).
- **연동:** 필요=동기 호출 / 반응=도메인 이벤트. **회계는 이벤트구독+설정형 posting 규칙테이블로만 연결**(GL 계정지식 회계에만). 이벤트는 같은 트랜잭션 동기 → 정합성+경량.

## AI (거버넌스 §8 + 메커니즘 AI-AGENT.md)
- **도구-우선:** AI = "말로 버튼 누르는 사용자". 도구=service 얇은 래퍼(스키마 자동생성).
- **학습:** 사실=RAG/라이브DB(학습0), 행동=주기적 LoRA+eval. 매일 파인튜닝 ❌. **자산=데이터셋**(모델은 교체가능 기판).
- **자율성:** 자동 posting + 불확실하면 되묻기 + 주/월 사람 감사 + 전건 감사로그.
- **보안 사슬:** §8.6 입력관문(격리·Default-Not-Indexed) → §8.4 수신분류(태그) → §8.5 권한 3축(판정) → §8.3 검색게이트(권한없는 데이터는 컨텍스트에 부재). **LLM은 보안경계 아님 — 코드에서 결정론적 통제.**
- **권한 3축:** scope(hr/finance/inventory/system) × level(1~3) × data_boundary(self/team/dept/all, reports_to 재사용). UI·AI·RAG 동일 적용.
- **모델:** 개발=Qwen2.5(4090). 출고=Llama 3.3 70B(미국·안전기본)+Qwen2.5-72B(성능) 둘 다 탑재, 고객 설치 시 선택. 범위=업무전용 기본+admin 일반비서 토글.

## 전역 정책 (POLICIES)
역분개only(삭제금지)·마감잠금 · gapless 채번(PREFIX-YYYY-NNNN) · 권한 4역할 기본값(정본=§8.5) · in-app+SSE 알림 · 야간백업+원클릭복원.

## 로드맵
Phase1 경량코어(전 사이클) → Phase2 에이전트 연결 → Phase3 문서파싱·분류·RAG질의 → GTM 온보딩/이행 → Phase4 자체 파인튜닝.

## 열린 항목 (소소)
- 모델 운영 기본값 벤치마크(Llama70B vs Qwen72B), 피크 동시 AI 사용자→Ollama/vLLM
- B그룹 후속(반품·재고실사·급여·예산) Phase 미정
- 필드 레벨 마감(상태전이도 일부)
