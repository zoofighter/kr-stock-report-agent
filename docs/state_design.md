# 멀티에이전트 State 설계

**작성일:** 2026-04-13  
**수정일:** 2026-04-13  
**버전:** 0.2 (Researcher / Analyst / Writer 3-에이전트 구조)

---

## 1. 설계 원칙

멀티에이전트에서 모든 에이전트가 하나의 State를 공유하면 다음 문제가 발생한다.

| 문제 | 설명 |
|------|------|
| **비대화** | 모든 내부 변수가 한 State에 쌓여 수십 개 필드 |
| **오염 위험** | 한 에이전트가 다른 에이전트 필드를 덮어쓸 수 있음 |
| **병렬 충돌** | Researcher 내부 병렬 노드가 동시에 State를 수정하면 race condition |
| **재사용 불가** | Researcher를 다른 프로젝트에서 쓰려면 SupervisorState 전체를 가져가야 함 |

**해결:** State를 2계층으로 분리한다.

```
SupervisorState  (조율용 — 패키지 단위 결과물만 저장)
    ↓ 입력 매핑 (필요한 필드만)
AgentPrivateState (에이전트 내부 전용 — 외부 접근 불가)
    ↓ 출력 매핑 (결과 패키지만 반환)
SupervisorState 업데이트
```

---

## 2. 에이전트 간 교환 패키지

에이전트 간 주고받는 단위를 **패키지(Package)**로 명확히 정의한다.

```python
from typing import TypedDict

class ResearchPackage(TypedDict):
    """Researcher → Supervisor 반환"""
    report_chunks: list[dict]       # RAPTOR 계층 메타 포함
    news_chunks: list[dict]         # 소스 신뢰도 메타 포함
    summaries: list[str]            # 리포트별 요약
    qa_pairs: list[dict]            # 자기 질문 + 답변
    advanced_qa_pairs: list[dict]   # 인터넷 검색 기반 QA

class AnalysisPackage(TypedDict):
    """Analyst → Supervisor 반환"""
    toc: list[dict]                 # [{"title": ..., "key_message": ...}]
    global_context_seed: str        # Writer 초기 global_context
```

---

## 3. SupervisorState — 조율용 공유 State

Supervisor가 직접 읽고 쓰는 State.  
에이전트 결과물을 **패키지 단위**로만 저장한다.

```python
class SupervisorState(TypedDict):
    # ── 입력 ──────────────────────────────────
    topic: str
    company_name: str
    ticker: str
    sector: str
    today: str

    # ── 에이전트 결과 패키지 ────────────────────
    research: ResearchPackage       # Researcher 출력
    analysis: AnalysisPackage       # Analyst 출력

    # ── 진행 상태 플래그 ────────────────────────
    research_done: bool
    analysis_done: bool
    writing_done: bool

    # ── 출력 ──────────────────────────────────
    final_report: str
```

**필드 수:** ~12개 (기존 단일 State ~25개 대비 절반)

---

## 4. 에이전트별 Private State

### 4.1 ResearcherState (Researcher 내부 전용)

```python
class ResearcherState(TypedDict):
    # 입력 (SupervisorState에서 매핑)
    topic: str
    company_name: str               # AdvancedQA 프롬프트에 필요
    ticker: str
    sector: str
    today: str
    report_date: str                # 가장 최근 리포트 발행일 (AdvancedQA 쿼터 계산에 필요)

    # 내부 — 리포트 수집
    file_paths: list[str]
    raw_texts: list[dict]
    parse_errors: list[str]
    raptor_chunks: list[dict]       # Level 0/1/2 계층 포함

    # 내부 — 뉴스 수집 (병렬 노드별 임시 저장)
    naver_raw: list[dict]
    google_raw: list[dict]
    ddg_raw: list[dict]
    blog_raw: list[dict]
    merged_news: list[dict]

    # 내부 — QA 생성
    grouped_by_report: dict
    qa_draft: list[dict]
    adv_qa_draft: list[dict]
    gap_analysis: str
    search_results: dict            # AdvancedQA 질문별 검색 결과

    # 출력 → ResearchPackage로 패킹
    report_chunks: list[dict]
    news_chunks: list[dict]
    summaries: list[str]
    qa_pairs: list[dict]
    advanced_qa_pairs: list[dict]
```

### 4.2 AnalystState (Analyst 내부 전용)

```python
class AnalystState(TypedDict):
    # 입력
    topic: str
    sector: str
    today: str
    report_date: str
    # ResearchPackage 언팩
    summaries: list[str]
    qa_pairs: list[dict]
    advanced_qa_pairs: list[dict]
    news_chunks: list[dict]

    # 내부 — TOC 생성
    rag_context: str                # 5개 컬렉션 병렬 검색 결과
    thinking_steps: list[str]       # CoT 중간 추론 (디버깅용)
    toc_draft: list[dict]           # 초안
    toc_iteration: int              # 재생성 횟수 (최대 3회)

    # 내부 — TOC 리뷰
    review_feedback: str
    review_approved: bool

    # 내부 — Human 편집
    human_edits: list               # Human이 수정한 항목

    # 출력 → AnalysisPackage로 패킹
    toc: list[dict]                 # 확정 목차
    global_context_seed: str
```

### 4.3 WriterState (Writer 내부 전용)

```python
class WriterState(TypedDict):
    # 입력
    toc: list[dict]
    global_context: str             # 섹션 간 일관성 유지 누적값
    # ResearchPackage 언팩
    report_chunks: list[dict]
    news_chunks: list[dict]
    qa_pairs: list[dict]
    advanced_qa_pairs: list[dict]

    # 내부 — 섹션 작성
    current_section_idx: int
    sub_queries: list[str]          # Multi-Query RAG용 서브 질문
    rag_results: list[dict]         # RAPTOR 레벨별 검색 결과
    section_draft: dict             # 현재 섹션 초안 (Structured Output)

    # 내부 — 통합 편집
    sections: list[dict]            # 전체 완성 섹션
    style_issues: list[str]         # 감지된 문체 불일치
    merged_draft: str               # 편집 완료 초안

    # 내부 — Human 검토
    human_edits: dict               # {section_idx: "수정 내용"}
    draft_approved: bool

    # 출력
    final_report: str
```

---

## 5. State 계층 요약

```
SupervisorState          ← ~12개 필드, 패키지 단위 관리
  │
  ├── ResearcherState    ← ~20개 필드, Researcher 전용
  ├── AnalystState       ← ~15개 필드, Analyst 전용
  └── WriterState        ← ~18개 필드, Writer 전용
```

| State | 필드 수 | 접근 주체 |
|-------|--------|----------|
| `SupervisorState` | 12개 | Supervisor만 |
| `ResearcherState` | 20개 | Researcher 내부만 |
| `AnalystState` | 15개 | Analyst 내부만 |
| `WriterState` | 18개 | Writer 내부만 |

---

## 6. 입출력 매핑 구현

```python
# Supervisor → Researcher 호출
def call_researcher(state: SupervisorState) -> dict:
    result: ResearcherState = researcher_graph.invoke(
        ResearcherState(
            topic=state["topic"],
            company_name=state["company_name"],   # AdvancedQA 프롬프트용
            ticker=state["ticker"],
            sector=state["sector"],
            today=state["today"],
            report_date="",                        # collect_reports 노드에서 채움
            # 내부 필드 초기화
            file_paths=[], raw_texts=[], parse_errors=[], raptor_chunks=[],
            naver_raw=[], google_raw=[], ddg_raw=[], blog_raw=[], merged_news=[],
            grouped_by_report={}, qa_draft=[], adv_qa_draft=[],
            gap_analysis="", search_results={},
            report_chunks=[], news_chunks=[], summaries=[],
            qa_pairs=[], advanced_qa_pairs=[]
        )
    )
    return {
        "research": ResearchPackage(
            report_chunks=result["report_chunks"],
            news_chunks=result["news_chunks"],
            summaries=result["summaries"],
            qa_pairs=result["qa_pairs"],
            advanced_qa_pairs=result["advanced_qa_pairs"],
        ),
        "research_done": True
    }

# Supervisor → Analyst 호출
def call_analyst(state: SupervisorState) -> dict:
    r = state["research"]
    result: AnalystState = analyst_graph.invoke(
        AnalystState(
            topic=state["topic"], sector=state["sector"],
            today=state["today"], report_date=get_latest_date(r["report_chunks"]),
            summaries=r["summaries"], qa_pairs=r["qa_pairs"],
            advanced_qa_pairs=r["advanced_qa_pairs"], news_chunks=r["news_chunks"],
            # 내부 필드 초기화
            rag_context="", thinking_steps=[], toc_draft=[], toc_iteration=0,
            review_feedback="", review_approved=False, human_edits=[],
            toc=[], global_context_seed=""
        )
    )
    return {
        "analysis": AnalysisPackage(
            toc=result["toc"],
            global_context_seed=result["global_context_seed"],
        ),
        "analysis_done": True
    }

# Supervisor → Writer 호출
def call_writer(state: SupervisorState) -> dict:
    r, a = state["research"], state["analysis"]
    result: WriterState = writer_graph.invoke(
        WriterState(
            toc=a["toc"], global_context=a["global_context_seed"],
            report_chunks=r["report_chunks"], news_chunks=r["news_chunks"],
            qa_pairs=r["qa_pairs"], advanced_qa_pairs=r["advanced_qa_pairs"],
            # 내부 필드 초기화
            current_section_idx=0, sub_queries=[], rag_results=[], section_draft={},
            sections=[], style_issues=[], merged_draft="",
            human_edits={}, draft_approved=False, final_report=""
        )
    )
    return {
        "final_report": result["final_report"],
        "writing_done": True
    }
```

---

## 7. 병렬 수집 시 State 충돌 방지

Researcher 내부에서 리포트 수집과 뉴스 수집을 병렬 실행할 때  
각 노드가 **서로 다른 필드**에만 쓰기 때문에 충돌이 없다.

```python
from langgraph.types import Send

def dispatch_collection(state: ResearcherState):
    """리포트 수집과 뉴스 수집 병렬 실행"""
    return [
        Send("collect_reports", {
            "topic": state["topic"], "ticker": state["ticker"]
        }),                              # → raptor_chunks, report_chunks
        Send("fetch_news", {
            "topic": state["topic"]
        }),                              # → naver_raw, google_raw, ... → news_chunks
    ]
    # generate_qa는 report_chunks 완료 후 순차 실행

# 충돌 없음: collect_reports → report_chunks 필드
#            fetch_news     → news_chunks 필드
```
