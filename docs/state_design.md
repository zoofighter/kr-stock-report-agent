# 멀티에이전트 State 설계

**작성일:** 2026-04-13

---

## 1. 단일 ReportState의 문제점

멀티에이전트 구조에서 모든 에이전트가 하나의 State를 공유하면 다음 문제가 발생한다:

| 문제 | 설명 |
|------|------|
| **비대화** | 모든 에이전트의 내부 변수가 한 State에 쌓여 수십 개 필드 |
| **오염 위험** | 한 에이전트가 실수로 다른 에이전트의 필드를 덮어쓸 수 있음 |
| **병렬 충돌** | ReportCollectAgent와 NewsAgent가 동시에 State를 수정하면 race condition 발생 |
| **테스트 어려움** | 에이전트 단독 테스트 시 불필요한 필드를 모두 채워야 함 |
| **재사용 불가** | 에이전트를 다른 프로젝트에 가져가면 ReportState 전체를 같이 가져가야 함 |

---

## 2. LangGraph 멀티에이전트 State 패턴

LangGraph는 **부모 그래프(Supervisor)와 서브그래프(Agent)가 각자의 State를 가질 수 있다.**  
서브그래프 호출 시 **입출력 매핑(input/output schema)**으로 필요한 필드만 주고받는다.

```
SupervisorState  ──입력 매핑──▶  AgentPrivateState
                 ◀──출력 매핑──  AgentPrivateState
```

이 방식으로 각 에이전트는 자신의 작업에 필요한 필드만 알면 된다.

---

## 3. State 계층 구조

```
SupervisorState (전체 공유 · 조율용)
  │
  ├── ReportCollectState  (서브그래프 내부 전용)
  ├── NewsState           (서브그래프 내부 전용)
  ├── QAState             (서브그래프 내부 전용)
  ├── AdvancedQAState     (서브그래프 내부 전용)
  ├── TOCState            (서브그래프 내부 전용)
  ├── ReviewerState       (서브그래프 내부 전용)
  ├── WriterState         (서브그래프 내부 전용)
  └── EditorState         (서브그래프 내부 전용)
```

---

## 4. SupervisorState — 전체 조율용 공유 State

Supervisor만 직접 읽고 쓰는 State.  
각 에이전트의 **결과물(output)** 만 저장한다. 내부 처리 과정은 포함하지 않는다.

```python
from typing import TypedDict, Annotated
from operator import add

class SupervisorState(TypedDict):
    # ── 입력 ──────────────────────────────────────────
    topic: str                      # 보고서 주제 (종목명, 테마)
    company_name: str               # 회사명
    ticker: str                     # 종목 코드
    sector: str                     # 섹터

    # ── 수집 에이전트 결과물 ───────────────────────────
    report_chunks: list[dict]       # ReportCollectAgent 출력
    news_chunks: list[dict]         # NewsAgent 출력
    summaries: list[str]            # QAAgent 출력
    qa_pairs: list[dict]            # QAAgent 출력
    advanced_qa_pairs: list[dict]   # AdvancedQAAgent 출력

    # ── 목차 에이전트 결과물 ───────────────────────────
    toc_draft: list[str]            # TOCAgent 출력
    review_feedback: str            # ReviewerAgent 출력
    toc_approved: bool              # Human 승인 여부
    toc: list[str]                  # 최종 확정 목차

    # ── 본문 에이전트 결과물 ───────────────────────────
    global_context: str             # WriterAgent가 누적
    sections: list[dict]            # WriterAgent 출력
    sections_done: bool             # 전체 섹션 완료 여부

    # ── 편집 결과물 ────────────────────────────────────
    merged_draft: str               # EditorAgent 출력

    # ── Human-in-the-Loop ──────────────────────────────
    draft_approved: bool            # Human 초안 승인 여부
    human_edits: dict               # Human 수정 요청

    # ── 출력 ──────────────────────────────────────────
    final_report: str               # 최종 보고서
```

---

## 5. 서브에이전트별 Private State

각 에이전트는 자신의 작업에만 필요한 필드를 가진다.

### 5.1 ReportCollectState

```python
class ReportCollectState(TypedDict):
    # 입력 (Supervisor로부터)
    topic: str
    ticker: str

    # 내부 처리용
    file_paths: list[str]           # 로드된 파일 경로 목록
    raw_texts: list[dict]           # 파일별 원문 텍스트
    parse_errors: list[str]         # 파싱 실패 파일 목록

    # 출력 (Supervisor로 반환)
    report_chunks: list[dict]       # 청크 + 날짜 가중치 메타
```

### 5.2 NewsState

```python
class NewsState(TypedDict):
    # 입력
    topic: str
    keywords: list[str]

    # 내부 처리용 (소스별 수집 결과 임시 저장)
    naver_raw: list[dict]
    google_raw: list[dict]
    ddg_raw: list[dict]
    blog_raw: list[dict]
    merged_raw: list[dict]          # 4개 소스 병합 결과
    dedup_done: bool                # 중복 제거 완료 여부

    # 출력
    news_chunks: list[dict]
```

### 5.3 QAState

```python
class QAState(TypedDict):
    # 입력
    report_chunks: list[dict]

    # 내부 처리용
    grouped_by_report: dict         # 리포트 단위로 그룹화된 청크
    current_report_idx: int         # 현재 처리 중인 리포트 인덱스

    # 출력
    summaries: list[str]
    qa_pairs: list[dict]
```

### 5.4 AdvancedQAState

```python
class AdvancedQAState(TypedDict):
    # 입력
    topic: str
    ticker: str
    sector: str
    report_date: str
    summaries: list[str]
    qa_pairs: list[dict]

    # 내부 처리용
    gap_analysis: str               # 갭 분석 결과
    generated_questions: list[dict] # 유형별 생성된 질문
    search_queries: dict            # 질문별 검색 쿼리
    search_results: dict            # 질문별 검색 결과

    # 출력
    advanced_qa_pairs: list[dict]
```

### 5.5 TOCState

```python
class TOCState(TypedDict):
    # 입력
    topic: str
    sector: str
    summaries: list[str]
    qa_pairs: list[dict]
    advanced_qa_pairs: list[dict]
    news_chunks: list[dict]

    # 내부 처리용
    rag_context: str                # RAG 검색 결과 종합
    thinking_steps: list[str]       # CoT 중간 추론 단계

    # 출력
    toc_draft: list[str]
```

### 5.6 ReviewerState

```python
class ReviewerState(TypedDict):
    # 입력
    toc_draft: list[str]
    topic: str
    today: str

    # 내부 처리용
    evaluation: dict                # 평가 기준별 점수
    # {"relevance": 4, "coverage": 3, "completeness": 5, ...}

    # 출력
    review_feedback: str            # "승인" or "재작성: <사유>"
    approved: bool
```

### 5.7 WriterState

```python
class WriterState(TypedDict):
    # 입력
    toc: list[str]
    global_context: str             # Supervisor로부터 최신값 주입
    current_section_idx: int
    report_chunks: list[dict]
    news_chunks: list[dict]
    qa_pairs: list[dict]
    advanced_qa_pairs: list[dict]

    # 내부 처리용
    rag_results: list[dict]         # 현재 섹션 RAG 검색 결과
    news_results: list[dict]        # 현재 섹션 뉴스 검색 결과
    section_keywords: list[str]     # 현재 섹션 키워드

    # 출력
    section_draft: dict             # {"title", "keywords", "draft", "sources"}
    updated_global_context: str     # 누적 후 반환
```

### 5.8 EditorState

```python
class EditorState(TypedDict):
    # 입력
    sections: list[dict]
    global_context: str

    # 내부 처리용
    style_issues: list[str]         # 감지된 문체 불일치 목록
    duplicate_passages: list[dict]  # 중복 구절 위치

    # 출력
    merged_draft: str
```

---

## 6. 입출력 매핑 구현

LangGraph에서 서브그래프 호출 시 State 필드를 매핑한다.

```python
from langgraph.graph import StateGraph

# Supervisor 그래프에 NewsAgent 서브그래프 연결
def call_news_agent(supervisor_state: SupervisorState) -> dict:
    """
    SupervisorState → NewsState 변환 후 서브그래프 호출
    결과를 SupervisorState 필드로 다시 매핑
    """
    input_state = NewsState(
        topic=supervisor_state["topic"],
        keywords=extract_keywords(supervisor_state["topic"]),  # 자동 키워드 추출
        # 내부 필드는 초기화
        naver_raw=[], google_raw=[], ddg_raw=[], blog_raw=[],
        merged_raw=[], dedup_done=False,
        news_chunks=[]
    )

    result: NewsState = news_agent_graph.invoke(input_state)

    # 필요한 필드만 SupervisorState로 반환
    return {"news_chunks": result["news_chunks"]}
```

```python
# WriterAgent는 섹션마다 호출 — global_context를 최신값으로 주입
def call_writer_agent(supervisor_state: SupervisorState) -> dict:
    idx = supervisor_state["current_section_idx"]

    input_state = WriterState(
        toc=supervisor_state["toc"],
        global_context=supervisor_state["global_context"],  # 최신 누적값
        current_section_idx=idx,
        report_chunks=supervisor_state["report_chunks"],
        news_chunks=supervisor_state["news_chunks"],
        qa_pairs=supervisor_state["qa_pairs"],
        advanced_qa_pairs=supervisor_state["advanced_qa_pairs"],
        # 내부 필드 초기화
        rag_results=[], news_results=[], section_keywords=[],
        section_draft={}, updated_global_context=""
    )

    result: WriterState = writer_agent_graph.invoke(input_state)

    # 섹션 추가 + global_context 업데이트
    updated_sections = supervisor_state["sections"] + [result["section_draft"]]
    return {
        "sections": updated_sections,
        "global_context": result["updated_global_context"],  # 누적 갱신
        "current_section_idx": idx + 1,
        "sections_done": (idx + 1) >= len(supervisor_state["toc"])
    }
```

---

## 7. 병렬 수집 시 State 충돌 방지

ReportCollectAgent, NewsAgent, QAAgent를 동시에 실행할 때  
각자 다른 State 필드에 쓰기 때문에 충돌이 없다.

```python
from langgraph.types import Send

def dispatch_collection(state: SupervisorState):
    return [
        Send("report_collect_agent", ReportCollectState(
            topic=state["topic"], ticker=state["ticker"],
            file_paths=[], raw_texts=[], parse_errors=[], report_chunks=[]
        )),
        Send("news_agent", NewsState(
            topic=state["topic"], keywords=[],
            naver_raw=[], google_raw=[], ddg_raw=[], blog_raw=[],
            merged_raw=[], dedup_done=False, news_chunks=[]
        )),
        # QAAgent는 report_chunks가 필요하므로 ReportCollect 완료 후 실행
    ]

# 각 에이전트가 반환하는 필드가 겹치지 않으므로 merge 시 충돌 없음
# report_collect → report_chunks
# news           → news_chunks
```

> **주의:** QAAgent는 `report_chunks`를 입력으로 받으므로  
> ReportCollectAgent 완료 후에 실행해야 한다. NewsAgent와만 병렬 가능.

---

## 8. State 구조 최종 요약

```
SupervisorState          ← Supervisor가 관리하는 전체 조율 State
  │
  │  입력 매핑 (필요한 필드만 전달)
  ▼
AgentPrivateState        ← 에이전트 내부 전용 (외부에서 직접 접근 불가)
  │
  │  출력 매핑 (결과 필드만 반환)
  ▼
SupervisorState 업데이트  ← 해당 에이전트의 결과 필드만 갱신
```

| State | 필드 수 | 접근 주체 |
|-------|--------|----------|
| `SupervisorState` | ~20개 | Supervisor + 매핑 함수 |
| `ReportCollectState` | 5개 | ReportCollectAgent 전용 |
| `NewsState` | 8개 | NewsAgent 전용 |
| `QAState` | 5개 | QAAgent 전용 |
| `AdvancedQAState` | 9개 | AdvancedQAAgent 전용 |
| `TOCState` | 8개 | TOCAgent 전용 |
| `ReviewerState` | 6개 | ReviewerAgent 전용 |
| `WriterState` | 10개 | WriterAgent 전용 |
| `EditorState` | 5개 | EditorAgent 전용 |
