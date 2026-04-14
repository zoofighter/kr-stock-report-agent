# Planner 추가 설계 검토

작성일: 2026-04-14

---

## 1. 현재 구조의 한계

현재 파이프라인에서 "방향 설정" 역할이 분산되어 있다.

```
Analyst
  assess_data     ← 데이터 충분성 평가
  extract_thesis  ← 논지 추출 (what)
  build_toc       ← 목차 생성 (structure)
  plan_sections   ← 섹션별 작성 가이드 (how per section)
Writer
  write_sections  ← 섹션별 독립 작성 (no cross-section awareness)
```

**문제점**:
- `extract_thesis` → `build_toc` → `plan_sections` 이 세 노드가 각각 독립 LLM 호출 → 전체 전략 일관성 부족
- `write_sections`는 섹션 간 흐름을 모름 (앞 섹션에서 뭘 썼는지)
- 리포트 전체의 "어떤 이야기를 어떻게 풀어낼 것인가"를 결정하는 노드가 없음

---

## 2. Planner의 역할 정의

> **Planner**: 실행(execution) 전에 전략(strategy)을 수립하는 노드.  
> 데이터를 직접 생성하지 않고, 이후 노드들이 따를 청사진을 만든다.

---

## 3. 삽입 위치 옵션 3가지

### Option A — Research Planner (Researcher 이전)

```
[NEW] research_planner
  ↓
Researcher Graph
  collect_reports → fetch_news || extract_issues
```

**역할**:
- 입력: company_name, ticker, sector
- 출력: `research_plan` — 집중 조사할 관점 (성장성/수익성/리스크/촉매), 예상 투자 각도
- 효과: fetch_news 쿼리, extract_issues 프롬프트가 이 plan을 참조

**장점**: 처음부터 방향 잡힘  
**단점**: 실제 리포트 내용을 보기 전이라 계획이 부정확할 수 있음  
**구현 난이도**: 낮음 (state에 `research_plan` 필드 추가만)

---

### Option B — Report Strategy Planner (Researcher → Analyst 사이)

```
Researcher Graph (완료)
  ↓
[NEW] report_strategy_planner
  ↓
Analyst Graph
  extract_thesis → build_toc → plan_sections
```

**역할**:
- 입력: L2 요약, issues 목록, news 요약
- 출력: `report_strategy` — 보고서 전체 방향성
  - `angle`: 어떤 각도로 접근할지 (예: "배당+재무안정성 중심", "AI 성장주 재평가")
  - `emphasis`: 강조할 논점 우선순위
  - `skip`: 덜 중요해서 간략히 다룰 영역
  - `narrative_hook`: 도입부에 쓸 핵심 메시지

**장점**: 실제 데이터 기반으로 정확한 전략 수립 가능  
**단점**: Analyst 그래프 입력 state 구조 변경 필요  
**구현 난이도**: 중간

---

### Option C — Narrative Planner (Analyst 마지막 노드)

```
Analyst Graph
  assess_data → extract_thesis → build_toc
  → [route] → review_toc / human_toc
  → plan_sections
  → [NEW] narrative_planner   ← Analyst 마지막 노드로 추가
  → END
        ↓
Writer Graph
  write_sections → assemble_report → save_report
```

> narrative_planner는 Analyst 그래프 내 마지막 노드로 추가한다.  
> main.py 변경 없이 Analyst 출력에 `narrative_plan`이 추가로 포함되어 Writer에 전달된다.

**역할**:
- 입력: thesis_list, toc, section_plans, global_context_seed
- 출력: `narrative_plan` — 섹션 간 흐름 설계
  - `section_transitions`: 각 섹션 사이 연결 문장 가이드
  - `cross_references`: "섹션 2의 수치는 섹션 4에서 재참조" 등 연결 지점
  - `emphasis_map`: 어느 섹션에 얼마나 길게 쓸지 (비중 재조정)
  - `opening_hook`: 보고서 서두 문장 초안
  - `closing_message`: 결론 핵심 메시지

**장점**: main.py 변경 없음, Writer 품질 즉각 향상  
**단점**: 이미 plan_sections와 역할 일부 겹침  
**구현 난이도**: 낮음 (Analyst graph.py + Writer state에 필드 추가)

---

## 4. 각 옵션 비교

| 항목 | A: Research Planner | B: Strategy Planner | C: Narrative Planner |
|------|--------------------|--------------------|---------------------|
| 삽입 위치 | Researcher 이전 | Researcher/Analyst 사이 | Analyst/Writer 사이 |
| 데이터 기반 | 없음 (추측) | L2+issues+news | thesis+toc+plans |
| 현재 코드 변경 | 소 | 중 | 소 |
| 즉각적 품질 향상 | 낮음 | 높음 | 높음 |
| plan_sections 와 겹침 | 없음 | 부분 | 부분 |
| 리포트 일관성 기여 | 간접 | 직접 | 직접 |

---

## 5. 권장 방향 — Option B + C 조합

### 단계 1 (단기): Narrative Planner (Option C) 먼저 구현

현재 `plan_sections`가 섹션별 가이드를 만들지만 섹션 **간** 흐름이 없다.  
`narrative_planner` 노드를 Analyst 마지막에 추가하면 Writer가 전체 맥락을 가진다.

```
Analyst Graph 수정안:
  assess_data → extract_thesis → build_toc
  → [route] → review_toc / human_toc
  → plan_sections
  → [NEW] narrative_planner   ← 추가
  → END
```

`narrative_planner` 출력 (`WriterState`에 추가):
```python
"narrative_plan": {
    "opening_hook":        "AI 에이전트 전환 시대, SKT의 포지셔닝을 재평가할 시점",
    "emphasis_map":        {"1": "heavy", "2": "medium", "3": "light", ...},
    "section_transitions": ["섹션1→2: 실적 개선에서 성장 동력으로 시선 이동", ...],
    "closing_message":     "배당+5G SA 성장이 동시에 실현될 경우 10만원 목표 달성 가능"
}
```

### 단계 2 (중기): Report Strategy Planner (Option B)

Researcher 완료 직후 별도 노드로 추가:

```
Researcher Graph (완료)
  ↓
[NEW] report_strategy_planner  (main.py에서 함수로 호출)
  ↓
Analyst Graph (strategy를 state에 담아 전달)
```

Strategy가 있으면 `extract_thesis`, `build_toc`가 더 일관된 방향으로 작동.

---

## 6. Narrative Planner 구현 스케치

### 6-1. state.py 추가

```python
class AnalystState(TypedDict):
    ...
    narrative_plan: dict   # narrative_planner 출력

class WriterState(TypedDict):
    ...
    narrative_plan: dict   # Analyst에서 전달받음
```

### 6-2. src/analyst/narrative_planner.py

```python
def narrative_planner(state: AnalystState) -> dict:
    toc           = state.get("toc", [])
    section_plans = state.get("section_plans", [])
    thesis_list   = state.get("thesis_list", [])
    company_name  = state["company_name"]

    llm = get_llm()

    prompt = f"""
{company_name} 보고서의 전체 서사 흐름을 설계하세요.

[목차]
{json.dumps(toc, ensure_ascii=False)}

[섹션별 핵심 메시지]
{json.dumps([{"order": s["order"], "title": s["title"], "key_message": s["key_message"]} for s in section_plans], ensure_ascii=False)}

[핵심 투자 논지]
{json.dumps(thesis_list, ensure_ascii=False)}

출력 (JSON):
{{
  "opening_hook": "보고서 첫 문장 또는 도입 메시지",
  "emphasis_map": {{"1": "heavy", "2": "medium", ...}},  // heavy=700자이상 / medium=500자 / light=300자
  "section_transitions": ["섹션1→2 연결 가이드", "섹션2→3 연결 가이드", ...],
  "closing_message": "결론 핵심 메시지 1문장"
}}
"""
    response = llm.invoke(prompt).content.strip()
    try:
        start = response.find("{")
        end   = response.rfind("}") + 1
        narrative_plan = json.loads(response[start:end])
    except Exception:
        narrative_plan = {"opening_hook": "", "emphasis_map": {}, "section_transitions": [], "closing_message": ""}

    return {"narrative_plan": narrative_plan}
```

### 6-3. src/analyst/graph.py 변경

```python
# 기존
builder.add_edge("plan_sections", END)

# 변경
builder.add_node("narrative_planner", narrative_planner)
builder.add_edge("plan_sections", "narrative_planner")
builder.add_edge("narrative_planner", END)
```

### 6-4. write_sections.py 활용

```python
narrative_plan = state.get("narrative_plan", {})
emphasis_map   = narrative_plan.get("emphasis_map", {})
transitions    = narrative_plan.get("section_transitions", [])

# 분량 조정
approx_length = emphasis_map.get(str(section["order"]), "medium")
length_guide  = {"heavy": 700, "medium": 500, "light": 300}.get(approx_length, 500)

# 섹션 전환 힌트 추가 (이전 섹션 존재 시)
transition_hint = transitions[section["order"] - 2] if section["order"] >= 2 else ""
```

---

## 7. 현재 구현 안 하는 이유와 조건

### 지금 당장 구현하지 않는 이유
1. `plan_sections`가 이미 유사한 역할을 부분 수행
2. Writer 품질이 아직 Planner보다 LLM 자체 한계에 더 의존
3. 추가 LLM 호출 → 실행 시간 증가 (종목당 +30~60초)

### 구현할 때 맞는 조건
- Writer가 섹션 간 연결 문장을 자연스럽게 쓰지 못한다는 피드백 반복 시
- 보고서를 10개 이상 생성해서 일관성 부족이 명확해졌을 때
- multi-company 비교 리포트로 확장 시 (Planner가 필수)
