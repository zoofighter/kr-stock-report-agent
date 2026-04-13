# 요건정의서 — 증권 리포트 기반 자동 보고서 생성 시스템

**작성일:** 2026-04-12  
**수정일:** 2026-04-13  
**버전:** 0.3 (Researcher / Analyst / Writer 3-에이전트 구조 반영)

---

## 1. 시스템 개요

증권사 리포트와 실시간 뉴스를 수집·분석하여, **LangGraph Supervisor + 3-에이전트** 구조로 구조화된 투자 보고서를 자동 생성하는 시스템.  
사용자(Human-in-the-Loop)가 목차 및 초안을 직접 검토·수정할 수 있는 인터랙티브 워크플로를 포함한다.

---

## 2. 디렉터리 구조

| 경로 | 용도 |
|------|------|
| `/user/boon/report` | 증권사 리포트 원본 파일 저장소 (입력) |
| `/user/boon/report_db/` | RAG 벡터 DB 저장소 (신규 생성) |

---

## 3. 시스템 아키텍처

### 3.1 에이전트 구성 — 외부 인터페이스

Supervisor가 3개 에이전트에 순차적으로 태스크를 위임한다.

```
Supervisor
  ├── ① Researcher  — 원자료 수집 전담
  ├── ② Analyst     — 분석 및 보고서 설계 전담
  └── ③ Writer      — 보고서 본문 생성 전담
```

### 3.2 에이전트 내부 구성 — 내부 구현

각 에이전트는 독립 서브그래프를 가지며 내부에서 세부 작업을 처리한다.

| 에이전트 | 내부 구성 요소 | 참고 문서 |
|---------|-------------|---------|
| **Researcher** | 리포트 수집, 뉴스 수집(병렬), QA 생성, AdvancedQA | `news_agent.md`, `qa_agent.md`, `advanced_qa_agent.md` |
| **Analyst** | TOC 생성, TOC 리뷰, Human 목차 승인 | `toc_agent.md` |
| **Writer** | 섹션 계획, 섹션 작성(반복), 통합 편집, Human 초안 승인 | `advanced_rag_design.md` |

### 3.3 RAG DB 컬렉션 구조

저장 경로: `/user/boon/report_db/`

| 컬렉션 | 저장 주체 | 저장 내용 |
|--------|----------|----------|
| `reports` | Researcher (리포트 수집) | 리포트 원문 청크 (Level 0/1/2 RAPTOR 계층) |
| `summaries` | Researcher (QA 생성) | 리포트별 LLM 생성 요약 |
| `qa_pairs` | Researcher (QA 생성) | LLM 자기 질문 + 답변 쌍 |
| `advanced_qa` | Researcher (AdvancedQA) | 인터넷 검색 기반 QA (출처 인용 포함) |
| `news` | Researcher (뉴스 수집) | 뉴스 청크 (메타: 수집일, 소스, 신뢰도 등급) |

---

## 4. 기능 요건

### 4.1 Researcher — 원자료 수집

**책임:** 모든 원자료(raw material) 수집 및 RAG 저장  
**출력:** `ResearchPackage {report_chunks, news_chunks, summaries, qa_pairs, advanced_qa_pairs}`

#### 리포트 수집
- `/user/boon/report` 내 파일 로드 및 섹션 단위 청크 분할
- 청크 메타데이터에 **발행일** 포함 필수
- RAPTOR 계층(Level 0 청크 → Level 1 중간요약 → Level 2 전체요약) 생성 및 저장
- 발행일 기준 **날짜 가중치** 적용: `w(d) = exp(-λ × 경과일수)`

#### 뉴스 수집 (병렬)
- 지원 소스 (우선순위 순): Naver 뉴스 API → Google News → DuckDuckGo → Naver 블로그
- 4개 소스 **Send API로 병렬 수집** 후 병합
- 소스별 신뢰도 등급 부여 (뉴스=0.8 / 블로그=0.5)
- 2단계 중복 제거: URL 기반 → 제목 유사도(0.9 이상) 기준
- 미니 Perplexity 방식으로 출처 인용 포함 요약 제공

#### QA 생성
- 리포트 청크 기반 요약 생성 → `summaries` 컬렉션 저장
- 요약 기반 LLM 자기 질문 N개 생성 (사실확인형 / 판단근거형 / 리스크형)
- 질문 + 답변을 `qa_pairs` 컬렉션 저장 → 동일 종목 재분석 시 재활용

#### AdvancedQA (인터넷 검색 기반)
- 리포트가 다루지 않은 6가지 유형의 질문 생성 (최신뉴스형 / 거시환경형 / 경쟁사비교형 / 정책규제형 / 미래전망형 / 투자자반응형)
- 인터넷 실시간 검색으로 답변 생성 (Perplexity 스타일, 출처 인용)
- 결과를 `advanced_qa` 컬렉션 저장

---

### 4.2 Analyst — 분석 및 보고서 설계

**책임:** ResearchPackage를 분석하여 보고서 목차(설계도) 생성  
**출력:** `AnalysisPackage {toc, global_context_seed}`

#### TOC 생성
- 5개 RAG 컬렉션 병렬 검색으로 풍부한 컨텍스트 확보
- 3단계 사고 프롬프트: 핵심 이슈 나열 → 목차 구조화 → 자기 검토(Self-Review)
- 섹터별 가이드라인 동적 주입 (반도체/바이오/배터리/자동차 등)
- 목차 초안 4~8개 항목 생성 (각 항목에 핵심 메시지 1줄 포함)

#### TOC 리뷰 (독립 LLM)
- TOC 생성 LLM과 독립된 인스턴스로 목차 품질 평가
- 평가 기준: 현시점 관련성 / 데이터 커버리지 / 항목 중복·누락 / 독자 완결성
- 최대 3회까지 재생성 요청 가능, 초과 시 Human에게 강제 전달

#### Human-in-the-Loop ① — 목차 검토
- 사용자가 직접 항목 추가·삭제·순서 변경 가능
- 사용자 승인 후 Writer 단계 진행

---

### 4.3 Writer — 보고서 본문 생성

**책임:** AnalysisPackage를 받아 보고서 본문 작성 및 편집  
**출력:** `final_report (Markdown / PDF)`

#### 섹션 작성 (Advanced RAG 적용)
- **Multi-Query RAG**: 섹션마다 5개 서브 질문 생성 후 병렬 검색
- **RAPTOR 계층 검색**: Level 0(수치) + Level 1(맥락) 혼합 활용
- **Structured Synthesis**: Pydantic 스키마 강제 출력 (요약/핵심포인트/수치/본문/출처)
- `global_context` 주입으로 섹션 간 논지 일관성 유지
- 섹션 완료 후 `global_context` 누적 업데이트

#### 통합 편집
- 전체 섹션 통합, 문체 통일, 중복 제거, 출처 인용 형식 정리

#### Human-in-the-Loop ② — 초안 검토
- 사용자가 섹션 단위로 재작성 요청 가능
- 재작성 요청 시 해당 섹션만 재작성 후 전체 편집 재실행

---

## 5. RAG 검색 전략

```
검색 스코어 = 벡터 유사도 × 날짜 가중치 × 소스 신뢰도

날짜 가중치:  w(d) = exp(-λ × 경과일수)
소스 신뢰도:  증권사 리포트=1.0 / 뉴스=0.8 / 블로그=0.5
```

| 에이전트 | RAPTOR 레벨 | 이유 |
|---------|-----------|------|
| Analyst (TOC) | Level 2 (전체요약) | 큰 그림 파악 |
| Writer (섹션) | Level 1 + Level 0 | 맥락 + 수치 |
| Researcher (QA) | Level 0 (청크) | 정확한 수치 답변 |

---

## 6. 비기능 요건

| 항목 | 요건 |
|------|------|
| **비용 최적화** | QA 생성 등 단순 작업은 소형 LLM 활용 |
| **병렬 처리** | Researcher 내부: 뉴스 4개 소스 + 리포트/뉴스/QA 동시 실행 |
| **확장성** | 3개 에이전트 인터페이스 고정, 내부 구현만 교체 가능 |
| **추적성** | 보고서 각 문장에 출처(리포트/뉴스) 인용 포함 |
| **재사용성** | Researcher를 다른 도메인(채권, 부동산)에 그대로 활용 가능 |

---

## 7. Memory & Store 적용

| 적용 위치 | 종류 | 목적 |
|----------|------|------|
| Analyst Human 목차 승인 | Checkpointer (interrupt) | 재개 필수 |
| Writer Human 초안 승인 | Checkpointer (interrupt) | 재개 필수 |
| Writer 섹션 반복 | Checkpointer | 에러 복구 |
| Researcher 뉴스 수집 | Store (news_cache, TTL 1h) | 중복 검색 방지 |
| Researcher QA 생성 | Store (qa_cache, TTL 7d) | LLM 비용 절감 |
| Analyst Human 목차 승인 | Store (toc_history, 영구) | 편집 패턴 학습 |
| 최종 출력 | Store (report_archive, 영구) | 보고서 아카이브 |

---

## 8. Human-in-the-Loop 인터페이스

| UI 옵션 | 장점 | 단점 |
|---------|------|------|
| CLI interrupt | 구현 간단, LangGraph 기본 지원 | UX 불편 |
| Streamlit | 시각적 편집 용이 | 별도 서버 필요 |
| Telegram 봇 | 모바일 승인 가능 | 텍스트 편집 제한 |

> **권장:** 초기에는 CLI interrupt → Streamlit 또는 Telegram으로 전환

---

## 9. 미결 사항

- [ ] Human-in-the-Loop UI 형태 최종 결정
- [ ] RAG DB 엔진 선택 (Chroma / Qdrant / FAISS)
- [ ] 뉴스 수집 주기 및 캐시 TTL 정책
- [ ] λ (날짜 가중치 감쇠 파라미터) 튜닝 기준
- [ ] Writer 섹션 작성 순차 vs 병렬 선택 기준

---

## 10. 구현 우선순위

1. Researcher 내부 구현 (리포트 수집 → 뉴스 수집 → QA)
2. RAG DB 컬렉션 구조 및 RAPTOR 인덱싱 확정
3. Analyst 내부 구현 (TOC 생성 → 리뷰 → Human 승인)
4. Writer 내부 구현 (Multi-Query + Structured Synthesis)
5. Supervisor 연결 및 전체 통합
6. Store 캐시 및 히스토리 적용
7. Human-in-the-Loop UI 연결
