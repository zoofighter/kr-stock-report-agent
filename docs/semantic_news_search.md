# 의미론적 뉴스 검색 설계 (Tavily 대체)

## 배경

현재 `fetch_news.py` 는 단일 고정 쿼리(`"{company_name} 주가 실적"`)를 4개 소스에 동일하게 사용한다.  
외부 AI 검색 API(Tavily) 없이, 이미 파이프라인에 있는 LLM + 임베딩 모델만으로 동등한 의미론적 검색을 구현할 수 있다.

---

## Tavily 의미론적 검색의 핵심 두 가지

```
1. 쿼리 확장   : 단일 키워드 → 의도를 커버하는 복수 쿼리 (LLM)
2. 의미 재랭킹 : 수집된 결과를 키워드 순이 아닌 의미 유사도 순으로 재정렬 (임베딩)
```

둘 다 현재 파이프라인의 `get_small_llm()` + `get_embeddings()` 로 구현한다.

---

## 구현 설계

### ① 쿼리 확장 — LLM이 검색어 4개 생성

```python
def _expand_queries(company_name: str, ticker: str, sector: str, llm) -> list[str]:
    prompt = (
        f"{company_name}({ticker}, {sector}) 최신 투자 뉴스를 수집하려 합니다.\n"
        "다음 관점을 커버하는 한국어 검색어 4개를 JSON 배열로만 출력하세요:\n"
        "- 실적·매출 전망\n"
        "- 섹터 시장 동향\n"
        "- 리스크·경쟁 이슈\n"
        "- 단기 주가 촉매 이벤트\n\n"
        '["검색어1", "검색어2", "검색어3", "검색어4"]'
    )
    raw = llm.invoke(prompt).content.strip()
    try:
        start, end = raw.find("["), raw.rfind("]") + 1
        return json.loads(raw[start:end])
    except Exception:
        return [f"{company_name} 주가 실적"]  # 폴백
```

**출력 예시** (삼성전자, 반도체):
```json
["삼성전자 반도체 실적 전망", "메모리 시장 HBM 수요",
 "삼성전자 경쟁 리스크 TSMC", "삼성전자 주주환원 배당 일정"]
```

---

### ② 의미 재랭킹 — 임베딩 코사인 유사도로 정렬

```python
import numpy as np

def _rerank(items: list[dict], query: str, emb_model) -> list[dict]:
    if not items:
        return []
    query_vec = np.array(emb_model.embed_query(query))
    texts = [f"{i['title']} {i['summary']}" for i in items]
    doc_vecs = np.array(emb_model.embed_documents(texts))

    # 코사인 유사도
    scores = doc_vecs @ query_vec / (
        np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(query_vec) + 1e-9
    )
    for item, score in zip(items, scores):
        # 기존 reliability 가중치 유지하면서 의미 유사도 반영
        item["relevance_score"] = round(float(score) * item.get("reliability", 1.0), 4)

    return sorted(items, key=lambda x: x["relevance_score"], reverse=True)
```

---

### ③ fetch_news() 변경 — 쿼리 확장 + 재랭킹 연결

```python
def fetch_news(state: ResearcherState) -> dict:
    ticker       = state["ticker"]
    company_name = state["company_name"]
    sector       = state["sector"]

    llm       = get_small_llm()
    emb_model = get_embeddings()

    # ① 쿼리 확장
    queries = _expand_queries(company_name, ticker, sector, llm)
    print(f"  확장 쿼리: {queries}")

    # ② 확장된 쿼리로 수집 (기존 소스 재사용)
    all_items = []
    for query in queries:
        all_items += search_naver_news(query, ticker)
        all_items += search_google_news(query, ticker)
        all_items += search_ddg(query, ticker)
    all_items += search_naver_blog(queries[0], ticker)  # 블로그는 첫 쿼리만

    # ③ 중복 제거 → 90일 필터 (기존 동일)
    deduped = deduplicate(all_items)
    cutoff  = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    deduped = [i for i in deduped if i.get("published_date", "9999") >= cutoff]

    # ④ 의미 재랭킹 — 종목 전체 의도 기준
    master_query = f"{company_name} {sector} 투자 핵심 이슈"
    reranked = _rerank(deduped, master_query, emb_model)

    print(f"  재랭킹 후 상위 30개 저장")
    final = reranked[:30]  # 상위 30개만 저장
    ...
```

---

## 현재 대비 효과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 검색어 수 | 1개 고정 | LLM이 생성한 4개 |
| 검색 관점 | 주가·실적만 | 실적 / 시장동향 / 리스크 / 촉매 |
| 결과 정렬 | 날짜순 (소스 reliability만 반영) | 의미 유사도 × reliability |
| 외부 의존성 | Naver API 키 | 추가 없음 (기존 LLM·임베딩 재사용) |
| 수집 기사 수 | 소스당 ~20개 | 쿼리 4개 × 소스 → 중복 제거 후 상위 30개 |

---

## 구현 시 고려사항

- **LLM 호출 비용**: 쿼리 확장 1회 + 재랭킹(임베딩) 추가 → 처리 시간 소폭 증가
- **임베딩 배치**: `embed_documents(texts)` 는 전체 리스트를 한 번에 처리하므로 개별 호출보다 효율적
- **블로그 쿼리**: 블로그는 스팸 필터가 있어 첫 번째 쿼리(실적 전망)만 사용, 나머지는 노이즈 증가 우려
- **`sector` 필드**: 현재 `ResearcherState` 에 있으므로 별도 변경 불필요
