# RAPTOR 설계 및 구현 상세

**작성일:** 2026-04-13  
**대상:** collect_reports 노드 내 RAPTOR 계층 인덱싱

---

## 1. RAPTOR란

**Recursive Abstractive Processing Tree Over Retrieval**

긴 문서를 계층적으로 요약하여 RAG 검색 정확도를 높이는 기법이다.  
원문 청크(Level 0) → 중간 요약(Level 1) → 전체 요약(Level 2) 의 3단계 계층을 ChromaDB에 함께 저장하고, 질문 유형에 따라 적절한 레벨에서 검색한다.

---

## 2. 왜 필요한가

### 일반 RAG의 한계

```
질문: "삼성전자의 전체적인 투자 논지는?"

청크 검색 결과 (Level 0):
  청크A: "1Q26 영업이익 6.2조원..."
  청크B: "HBM3E ASP +15% 전망..."
  청크C: "목표주가 95,000원..."

→ 단편적 수치만 나옴, 전체 맥락 파악 불가
→ "왜 매수인가"에 대한 논거 구성 불가
```

### RAPTOR의 해결

```
질문: "삼성전자의 전체적인 투자 논지는?"

Level 2 검색 결과:
  "HBM 공급 확대와 AI 수요 급증으로 반도체 실적이
   2026년 사상 최대 전망. 메모리 ASP 상승 지속으로
   영업이익률 30% 돌파 예상. 목표주가 95,000원."

→ 한 문장에 맥락 + 논거 + 수치 모두 포함
```

---

## 3. 3단계 계층 구조

```
원문 PDF
    │
    ▼ 800자씩 분할 (RecursiveCharacterTextSplitter)
┌──────────────────────────────────────────────────┐
│  Level 0: 원문 청크                               │
│  [청크1][청크2][청크3][청크4][청크5]               │
│  [청크6][청크7][청크8][청크9][청크10]              │
│  ...                                             │
│  특징: 원문 그대로, 수치/날짜/출처 보존             │
│  용도: 구체적 수치 확인, 출처 인용                  │
└──────────────────────────────────────────────────┘
    │ 5개씩 묶어 LLM 요약 (CLUSTER_SIZE=5)
    ▼
┌──────────────────────────────────────────────────┐
│  Level 1: 중간 요약                               │
│  [요약A: 청크1~5 압축]                            │
│  [요약B: 청크6~10 압축]                           │
│  ...                                             │
│  특징: 섹션 수준 논지, 핵심 수치 포함               │
│  용도: 섹션별 논거 파악, 판단 근거형 QA             │
└──────────────────────────────────────────────────┘
    │ Level 1 전체를 LLM으로 최종 요약
    ▼
┌──────────────────────────────────────────────────┐
│  Level 2: 전체 요약 (리포트당 1개)                 │
│  [투자 논지 2~3문장]                              │
│  특징: 리포트 전체 핵심 1개 문장                    │
│  용도: TOC 생성, 종목 비교, 전체 맥락 파악           │
└──────────────────────────────────────────────────┘
```

---

## 4. 구현 코드 위치

**파일:** `src/researcher/collect_reports.py`

| 함수 | 라인 | 역할 |
|------|------|------|
| `make_chunks()` | ~L60 | Level 0 원문 청크 생성 |
| `summarize_cluster()` | L100~108 | Level 1: 청크 5개 → 요약 1개 (LLM 호출) |
| `summarize_all()` | L111~118 | Level 2: Level 1 전체 → 최종 요약 (LLM 호출) |
| `build_raptor()` | L121~172 | RAPTOR 전체 조립 및 반환 |

---

## 5. 핵심 코드 흐름

```python
def build_raptor(chunks, ticker):
    llm = get_small_llm()   # gemma4:26b

    # ── Level 1 ──────────────────────────────────
    for i in range(0, len(chunks), CLUSTER_SIZE=5):
        cluster = chunks[i : i+5]           # 청크 5개 슬라이싱
        summary = summarize_cluster(cluster) # LLM 호출 1회 ← 병목
        level1_chunks.append({
            "id":   f"l1_{ticker}_{i:05d}",
            "text": summary,
            "metadata": {"raptor_level": 1, ...}
        })

    # ── Level 2 ──────────────────────────────────
    top_summary = summarize_all(level1_texts) # LLM 호출 1회
    level2_chunks = [{
        "id":   f"l2_{ticker}_top",
        "text": top_summary,
        "metadata": {"raptor_level": 2, ...}
    }]

    return level1_chunks, level2_chunks
```

---

## 6. LLM 호출 횟수 공식

```
L0 청크 수 = N
Level 1 LLM 호출 수 = ceil(N / 5)    # 순차 실행
Level 2 LLM 호출 수 = 1
─────────────────────────────────────
총 LLM 호출 수 = ceil(N/5) + 1
```

---

## 7. 성능 실측 결과 (2026-04-13)

**환경:** gemma4:26b (17GB, Ollama v0.20.5, MacOS)

| 작업 | 콜드 스타트 | 웜 (메모리 상주) |
|------|-----------|----------------|
| LLM 호출 1회 (gemma4:26b, 요약) | 25.7초 | **13.1초** |
| 임베딩 20개 (gte-qwen2) | — | 7.7초 (개당 0.38초) |

> 이전 측정값 736초는 `qwen3.5:27b` 콜드 스타트(모델 디스크→메모리 로딩) 포함 수치였으므로 제외.  
> 실제 운영 시 모델은 메모리에 상주하므로 웜 시간 기준이 적절하다.

### 파일 수별 예상 소요 시간 (웜 기준, 13초/회)

| 파일 수 | L0 청크 수 (추정) | L1 LLM 호출 | 예상 시간 |
|---------|-----------------|-------------|---------|
| 1개     | 3개             | 1회         | ~13초   |
| 10개    | 30개            | 6회         | ~78초   |
| 50개    | 150개           | 30회        | ~6.5분  |
| 100개   | 300개           | 60회        | ~13분   |

**결론: 100개 파일 기준 약 13분으로 실용적인 수준이다. 단, 첫 실행(콜드 스타트)은 약 2배 소요.**

---

## 8. 검색 시 레벨 선택 전략

```python
# 설계 기준 (langgraph_design.md)

# Researcher QA 생성 → 수치 정확성 우선
search("reports", question, ticker, level=0)

# Analyst TOC 생성 → 전체 맥락 파악
search("reports", topic, ticker, level=2)

# Writer 섹션 작성 → 맥락 + 수치 혼합
search("reports", section_title, ticker, level=1)  # 논거
search("reports", keyword, ticker, level=0)         # 수치
```

---

## 9. 현재 구현의 한계 (단순화 지점)

### 9.1 순서 기반 클러스터링 (구현됨)
현재는 청크를 순서대로 5개씩 묶어 요약한다.

```
[청크1~5] → 요약A
[청크6~10] → 요약B
```

### 9.2 의미 기반 클러스터링 (원래 RAPTOR 논문)
원래 RAPTOR는 임베딩 유사도 기반으로 관련 청크끼리 묶는다.

```python
# 원래 RAPTOR 방식 (미구현)
embeddings = embed_all_chunks(chunks)
clusters = UMAP(n_components=2).fit_transform(embeddings)
labels = GaussianMixture().fit_predict(clusters)
# 같은 label끼리 묶어 요약
```

Phase 1에서는 구현 복잡도 때문에 순서 기반으로 단순화했다.

---

## 10. 실용적 운영 방안

### Option A: RAPTOR 제거 (즉시 적용 가능)
Level 0 청크만 저장. Analyst/Writer 구현 시 필요해지면 그때 추가.

```python
# collect_reports() 에서 build_raptor() 호출 제거
all_chunks = l0_chunks  # l1, l2 없이 운영
```

**장점:** 처리 시간 대폭 단축 (LLM 호출 0회)  
**단점:** TOC 생성 시 전체 맥락 검색 불가, Writer 섹션 요약 품질 저하

### Option B: 파일 수 제한 (현실적 절충)
최신 N개 파일만 RAPTOR 처리.

```python
# 최신 30개 파일만 처리
matched = sorted(matched, reverse=True)[:30]
```

**장점:** RAPTOR 유지하면서 처리 시간 제어 가능  
**단점:** 오래된 리포트 맥락 누락

### Option C: 소형 임베딩 모델로 Level 1만 생성
Level 2 요약 생략, Level 1만 빠르게 생성.

```python
# summarize_all() 호출 제거
return level1_chunks, []   # level2 없이 반환
```

### Option D: 외부 API 모델 활용 (장기)
Gemini Flash, Claude Haiku 등 빠른 API 모델로 RAPTOR 생성.  
비용은 발생하지만 속도 문제 해결.

---

## 11. 다른 에이전트와의 연결

```
collect_reports (Researcher)
    └─► ChromaDB "reports" 컬렉션
            │
            ├── Level 0 ◄── generate_qa (수치 검색)
            ├── Level 1 ◄── Writer (섹션 작성)
            └── Level 2 ◄── Analyst TOCAgent (목차 생성)
```

---

## 12. 향후 개선 방향

1. **배치 처리**: Level 1 LLM 호출을 비동기(asyncio)로 병렬화
2. **캐시 활용**: 이미 구현된 `count_by_ticker()` 스킵 로직 활용
3. **의미 기반 클러스터링**: UMAP + GMM으로 관련 청크끼리 묶기
4. **소형 전용 요약 모델**: 3B~7B 수준 요약 전용 모델 도입
