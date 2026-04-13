# 요건정의서 — 증권 리포트 기반 자동 보고서 생성 시스템

**작성일:** 2026-04-12  
**수정일:** 2026-04-13  
**버전:** 0.2 (멀티에이전트 구조 반영)

---

## 1. 시스템 개요

증권사 리포트와 실시간 뉴스를 수집·분석하여, **LangGraph Supervisor + Subagent** 구조로 구조화된 투자 보고서를 자동 생성하는 시스템.  
사용자(Human-in-the-Loop)가 목차 및 초안을 직접 검토·수정할 수 있는 인터랙티브 워크플로를 포함한다.

---

## 2. 디렉터리 구조

| 경로 | 용도 |
|------|------|
| `/user/boon/report` | 증권사 리포트 원본 파일 저장소 (입력) |
| `/user/boon/report_db/` | RAG 벡터 DB 저장소 (신규 생성) |

---

## 3. 시스템 아키텍처

### 3.1 멀티에이전트 구성

Supervisor 에이전트가 전체 상태를 판단하여 서브에이전트에 태스크를 위임한다.

```
Supervisor
  ├── ① ReportCollectAgent  — 리포트 수집 및 RAG 저장
  ├── ① NewsAgent           — 뉴스 수집 및 RAG 저장       ← 병렬 실행
  ├── ① QAAgent             — 자기 질문 생성 및 RAG 저장
  ├── ② TOCAgent            — 목차 초안 생성
  ├── ② ReviewerAgent       — 목차 적합성 평가
  ├── ③ WriterAgent         — 섹션별 초안 작성
  └── ③ EditorAgent         — 전체 통합 편집
```

### 3.2 RAG DB 컬렉션 구조

저장 경로: `/user/boon/report_db/`

| 컬렉션 | 저장 주체 | 저장 내용 |
|--------|----------|----------|
| `reports` | ReportCollectAgent | 리포트 원문 청크 (메타: 발행일, 출처, 종목) |
| `summaries` | QAAgent | 리포트별 LLM 생성 요약 |
| `qa_pairs` | QAAgent | LLM 자기 질문 + 답변 쌍 |
| `news` | NewsAgent | 뉴스 청크 (메타: 수집일, 소스, 신뢰도 등급) |

---

## 4. 기능 요건

### 4.1 ReportCollectAgent — 리포트 수집

- `/user/boon/report` 내 파일 로드 및 섹션 단위 청크 분할
- 청크 메타데이터에 **발행일** 포함 필수
- 발행일 기준 **날짜 가중치** 적용: `w(d) = exp(-λ × 경과일수)`
- 처리 결과를 RAG `reports` 컬렉션에 저장

### 4.2 NewsAgent — 뉴스 수집

- 지원 소스 (우선순위 순):
  1. Naver 뉴스 API
  2. Google News
  3. DuckDuckGo 뉴스
  4. Naver 블로그
- 4개 소스를 **Send API로 병렬 수집** 후 병합
- 소스별 신뢰도 등급 부여: 뉴스=0.8 / 블로그=0.5
- 중복 뉴스 필터링 (단기 캐싱)
- 미니 Perplexity 방식 — 출처 인용 포함 요약 제공
- 처리 결과를 RAG `news` 컬렉션에 저장

### 4.3 QAAgent — 분석 및 질문 생성

- 리포트 청크 기반 요약 생성 → `summaries` 컬렉션 저장
- 요약 기반 LLM 자기 질문 N개 생성 (소형 모델 활용 가능)
- 질문 + 답변을 `qa_pairs` 컬렉션 저장
- 이후 동일 종목/테마 분석 시 기존 QA 재활용

> ※ ReportCollectAgent, NewsAgent, QAAgent는 Supervisor로부터 **동시에 실행**된다.

### 4.4 TOCAgent — 목차 생성

- RAG(`reports`, `news`, `qa_pairs`) 검색 결과를 종합하여 목차 초안 생성 (4~8개 항목)
- Chain-of-Thought + 현재 날짜 컨텍스트를 프롬프트에 주입하여 현시점 적합성 확보
- ReviewerAgent의 피드백 반영 시 재생성

### 4.5 ReviewerAgent — 목차 검토

- TOCAgent와 독립된 LLM 인스턴스로 목차 품질 평가
- 평가 기준:
  - 현시점(날짜) 관련성
  - 수집 데이터로 작성 가능한지 여부
  - 항목 간 중복·누락
  - 독자 관점 완결성
- 출력: `"승인"` 또는 `"재작성: <사유> / <개선안>"`

### 4.6 Human-in-the-Loop ① — 목차 검토

- ReviewerAgent 승인 후 사용자에게 목차 초안 제시
- 사용자가 직접 항목 추가·삭제·순서 변경 가능
- 사용자 승인 후 WriterAgent 단계 진행

### 4.7 WriterAgent — 보고서 본문 작성

- 확정된 목차 기준으로 섹션별 순차 초안 작성
- 각 섹션 작성 시:
  - RAG 검색 (날짜 가중치 + 소스 신뢰도 적용)
  - 최신 뉴스 재검색
  - `global_context` 주입으로 섹션 간 논지 일관성 유지
- 섹션 완료 후 `global_context` 누적 업데이트

**LangGraph State `global_context` 필드:**  
이전 섹션의 핵심 논지를 누적하여 다음 섹션 생성 시 주입. 보고서 전체 일관성 확보.

### 4.8 EditorAgent — 통합 편집

- 전체 섹션 초안 통합
- 섹션 간 문체 통일, 중복 내용 제거
- 출처 인용 형식 정리
- 서론·결론 연결 자연스럽게 보완

### 4.9 Human-in-the-Loop ② — 초안 검토

- EditorAgent 완료 후 사용자에게 전체 초안 제시
- 사용자가 섹션 단위로 재작성 요청 가능
- 재작성 요청 시 해당 섹션만 WriterAgent로 재전달
- 사용자 승인 후 최종 보고서 출력

---

## 5. RAG 검색 전략

```
검색 스코어 = 벡터 유사도 × 날짜 가중치 × 소스 신뢰도

날짜 가중치:  w(d) = exp(-λ × 경과일수)   # λ는 튜닝 파라미터
소스 신뢰도:  증권사 리포트=1.0 / 뉴스=0.8 / 블로그=0.5
```

---

## 6. 비기능 요건

| 항목 | 요건 |
|------|------|
| **비용 최적화** | 요약·질문 생성 등 단순 작업은 소형 LLM 모델 활용 |
| **병렬 처리** | 수집 3개 에이전트 및 뉴스 4개 소스를 Send API로 동시 실행 |
| **확장성** | 뉴스 소스 추가가 용이한 플러그인 구조 (에이전트 단위 독립) |
| **재현성** | 목차 생성 시 날짜 컨텍스트 주입으로 현시점 일관성 유지 |
| **추적성** | 보고서 각 문장에 출처(리포트/뉴스) 인용 포함 |
| **재사용성** | 각 서브에이전트는 독립 그래프로 다른 프로젝트에서도 활용 가능 |

---

## 7. Human-in-the-Loop 인터페이스 옵션

| UI 옵션 | 장점 | 단점 |
|---------|------|------|
| CLI interrupt | 구현 간단, LangGraph 기본 지원 | UX 불편 |
| Streamlit | 시각적 편집 용이 | 별도 서버 필요 |
| Telegram 봇 | 모바일 승인 가능 | 텍스트 편집 제한 |

> **권장:** 초기에는 CLI interrupt로 구현 후, Streamlit 또는 Telegram으로 전환

---

## 8. 미결 사항

- [ ] Human-in-the-Loop UI 형태 최종 결정 (CLI / Streamlit / Telegram)
- [ ] RAG DB 엔진 선택 (Chroma / Qdrant / FAISS 등)
- [ ] 뉴스 수집 주기 및 캐시 TTL 정책
- [ ] 날짜 가중치 λ 파라미터 튜닝 기준
- [ ] ReviewerAgent 모델 선택 (메인 모델과 동일 vs 별도 소형 모델)
- [ ] 섹션 작성 순차 vs 병렬 선택 기준 (문맥 일관성 vs 속도)

---

## 9. 구현 우선순위

1. RAG DB 컬렉션 구조 및 엔진 확정
2. `ReportCollectAgent` + `NewsAgent` + `QAAgent` 개별 구현 및 저장 확인
3. `TOCAgent` + `ReviewerAgent` 연결 (피드백 루프 검증)
4. `WriterAgent` — `global_context` 누적 동작 검증
5. `EditorAgent` 구현 및 통합 편집 품질 확인
6. `Supervisor` 추가하여 전체 통합
7. 병렬 수집 (Send API) 적용
8. Human-in-the-Loop 인터페이스 연결
