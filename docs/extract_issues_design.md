# 핵심 이슈 추출 설계 (extract_issues)

**작성일:** 2026-04-13  
**소속:** Researcher 서브그래프 — generate_qa 대체

---

## 1. 설계 배경

기존 `generate_qa` 노드는 리포트 내용을 기반으로 Q&A 9개를 생성했다.  
문제점:
- 질문 틀(사실확인/판단근거/리스크)이 고정되어 리포트 핵심을 못 짚을 수 있음
- `valuation` 범주(목표주가/투자의견)는 대부분 매수 의견으로 정보 가치가 낮음
- Writer/Analyst가 TOC 설계에 활용하기 어려운 형태

**변경:** Q&A 생성 → 카테고리별 핵심 이슈 추출

---

## 2. 이슈 카테고리

| 카테고리 | 설명 | 예시 |
|---------|------|------|
| `growth` | 수치 기반 성장 동력 | HBM 매출 +40%, 영업이익 6.2조, ASP +15% |
| `risk` | 하방 리스크, 불확실성 | 환율 하락, 경쟁사 추격, 수요 둔화 |
| `catalyst` | 단기 주가 촉매·이벤트 | 실적 발표, 신제품 출시, 고객사 발주 |
| `quality` | 질적 경쟁력 요소 | 기술 우위, 고객 관계, 경영 전략 변화 |

> **valuation 제외 이유:** 목표주가/투자의견은 대부분 매수 의견으로 정보 가치 낮음.  
> 수치(목표주가, PER 등)는 `growth` 또는 `catalyst` 에서 필요 시 포함.

---

## 3. 처리 흐름

```
collect_reports
    │ L0 청크 + L1 요약
    ▼
extract_issues
    │
    ├── 1. 리포트별 이슈 추출 (LLM, 소형 모델)
    │       소스 파일별 L1 청크 → 이슈 JSON 생성
    │
    ├── 2. 종목 전체 이슈 통합 (LLM, 소형 모델)
    │       중복 제거 + 중요도 순 정렬
    │
    └── 3. ChromaDB 저장
            issues 컬렉션 upsert
```

---

## 4. 핵심 프롬프트

### 4.1 리포트별 이슈 추출

```python
prompt = (
    f"당신은 증권사 리포트를 분석하는 투자 리서치 전문가입니다.\n"
    f"아래 {company_name}({ticker}) 리포트를 읽고 "
    f"투자 판단에 중요한 핵심 이슈를 카테고리별로 추출하세요.\n\n"
    f"[리포트 내용]\n{{content}}\n\n"
    "카테고리:\n"
    "- growth: 수치 기반 성장 동력 (매출, 이익, 점유율, ASP 등 수치 포함)\n"
    "- risk: 하방 리스크, 불확실성, 경쟁 위협\n"
    "- catalyst: 단기 주가 촉매, 이벤트, 출시 일정, 실적 발표\n"
    "- quality: 질적 경쟁력 요소 (기술 우위, 고객 관계, 경영 전략 변화, 산업 구조 변화)\n\n"
    "조건:\n"
    "- 각 카테고리 최대 3개\n"
    "- detail에 수치나 구체적 근거 반드시 포함\n"
    "- importance: 1=가장 중요 (숫자 작을수록 중요)\n\n"
    "출력 형식 (JSON 배열만, 다른 텍스트 없이):\n"
    '[\n'
    '  {"category": "growth", "issue": "HBM3E 공급 확대",\n'
    '   "detail": "2026년 HBM 매출 +40% 전망, ASP 15% 상승 지속", "importance": 1},\n'
    '  {"category": "quality", "issue": "엔비디아 독점 공급 관계 유지",\n'
    '   "detail": "HBM4 사전 인증 통과, 경쟁사 대비 6개월 리드타임 우위", "importance": 1},\n'
    '  {"category": "risk", "issue": "중국 메모리 업체 추격",\n'
    '   "detail": "CXMT DDR5 양산 본격화, 범용 DRAM 가격 압박 우려", "importance": 2},\n'
    '  ...\n'
    ']'
)
```

### 4.2 종목 전체 이슈 통합

```python
prompt = (
    f"아래는 {company_name}({ticker})에 대한 여러 리포트에서 추출한 이슈 목록입니다.\n"
    "중복을 제거하고 중요도 순으로 통합 정리하세요.\n\n"
    "규칙:\n"
    "- 같은 의미의 이슈는 하나로 합칠 것\n"
    "- 수치가 다를 경우 가장 최신 리포트 기준 수치 사용\n"
    "- 카테고리별 최대 5개로 제한\n\n"
    f"[이슈 목록]\n{{issues_json}}\n\n"
    "출력 형식 (JSON 배열만):\n"
    '[\n'
    '  {"category": "...", "issue": "...", "detail": "...", "importance": 1},\n'
    '  ...\n'
    ']'
)
```

---

## 5. ChromaDB 저장 스키마 (issues 컬렉션)

```python
{
    "id":   "issue_{ticker}_{category}_{importance:02d}",
    "text": "{issue} — {detail}",   # 벡터 검색용 본문
    "metadata": {
        "ticker":         "005930",
        "category":       "growth",      # growth / risk / catalyst / quality
        "issue":          "HBM3E 공급 확대",
        "detail":         "2026년 HBM 매출 +40% 전망, ASP 15% 상승",
        "importance":     1,             # int, 1=최고
        "source":         "26.04.07_삼성전자_키움증권_....pdf",
        "published_date": "2026-04-07",
    }
}
```

---

## 6. Analyst 활용 방안

```
issues 컬렉션 (importance ASC 조회)
    │
    ├── growth   이슈 → 본론 "성장 동력" 섹션
    ├── quality  이슈 → 본론 "경쟁 우위" 섹션
    ├── risk     이슈 → "리스크 요인" 섹션
    └── catalyst 이슈 → "투자 포인트" 섹션
```

SQL 조회 예시:
```sql
SELECT
    MAX(CASE WHEN em.key = 'category'  THEN em.string_value END) AS category,
    MAX(CASE WHEN em.key = 'issue'     THEN em.string_value END) AS issue,
    MAX(CASE WHEN em.key = 'detail'    THEN em.string_value END) AS detail,
    MAX(CASE WHEN em.key = 'importance' THEN em.int_value   END) AS importance
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
WHERE c.name = 'issues'
GROUP BY e.embedding_id
HAVING MAX(CASE WHEN em.key = 'ticker' THEN em.string_value END) = '005930'
ORDER BY category, importance;
```

---

## 7. 구현 파일

| 파일 | 변경 내용 |
|------|---------|
| `src/researcher/extract_issues.py` | 신규 생성 (generate_qa.py 대체) |
| `src/researcher/graph.py` | generate_qa → extract_issues 교체 |
| `src/state.py` | `qa_pairs` → `issues` 필드 교체 |
