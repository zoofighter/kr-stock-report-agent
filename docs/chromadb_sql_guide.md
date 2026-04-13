# ChromaDB SQLite 구조 및 SQL 조회 가이드

**작성일:** 2026-04-13  
**DB 경로:** `/Users/boon/report_db/chroma.sqlite3`

---

## 1. ChromaDB vs 관계형 DB 비교

ChromaDB는 벡터 데이터베이스다. 내부 저장소로 SQLite를 사용하지만,  
`reports`, `summaries` 같은 이름의 테이블을 직접 생성하지 않는다.  
대신 **컬렉션(Collection)** 이라는 개념으로 데이터를 그룹화한다.

```
관계형 DB (MySQL 등)              ChromaDB
──────────────────────           ──────────────────────
테이블 = 데이터 단위              컬렉션 = 데이터 단위
CREATE TABLE reports              client.create_collection("reports")
SELECT * FROM reports             collection.query(query_embeddings=[...])
인덱스 = B-Tree                   인덱스 = HNSW (벡터 근접 탐색)
```

---

## 2. SQLite 내부 테이블 구조 (총 21개)

| 테이블명 | 역할 |
|---------|------|
| `collections` | 컬렉션 목록 (name, UUID) |
| `segments` | 컬렉션당 2개 세그먼트 (VECTOR / METADATA) |
| `embeddings` | 벡터 레코드 (embedding_id = 우리가 저장한 id) |
| `embedding_metadata` | 메타데이터 key/value (EAV 방식) |
| `embedding_fulltext_search` | 원문 텍스트 전문 검색용 FTS5 테이블 |
| `migrations` | DB 스키마 버전 이력 |

---

## 3. 테이블 관계도

```
collections
  id (UUID)  ←─────────────────────────────┐
  name                                      │
       │                                    │
       ▼ id = segments.collection           │
segments                                    │
  id (UUID)  ←──────────────┐              │
  scope: VECTOR / METADATA   │              │
  collection: UUID ──────────┼──────────────┘
       │                     │
       ▼ id = embeddings.segment_id
embeddings
  id (INTEGER) ←─────────────────────┐
  segment_id: UUID                    │
  embedding_id: TEXT  (우리가 저장한 id)│
  created_at                          │
       │                              │
       ▼ id = embedding_metadata.id   │
embedding_metadata                    │
  id (INTEGER) ──────────────────────┘
  key:          "ticker" / "raptor_level" / "published_date" / ...
  string_value: TEXT    (문자열 메타데이터)
  int_value:    INTEGER (정수 메타데이터)
  float_value:  REAL    (실수 메타데이터)
```

> **EAV(Entity-Attribute-Value) 패턴**: 메타데이터를 하나의 테이블에  
> key/value 쌍으로 저장. 컬럼 수를 고정하지 않아 유연하지만  
> 조회 시 GROUP BY + CASE WHEN 조합이 필요하다.

---

## 4. 실용 SQL 쿼리 모음

### 4.1 컬렉션 목록 조회

```sql
SELECT name, id FROM collections;
```

**실행 결과:**
```
reports   | 10ca39cf-51bd-4b34-ab2f-c1a4e0963a1c
summaries | 2ccd027d-6db0-485f-b6ba-8d58cf758d29
qa_pairs  | 0a479f0d-5a58-4b12-aa5b-39c308881bec
```

---

### 4.2 컬렉션별 저장 건수

```sql
SELECT c.name, COUNT(e.id) as cnt
FROM collections c
JOIN segments s    ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e  ON e.segment_id = s.id
GROUP BY c.name;
```

**실행 결과 (2026-04-13 기준):**
```
qa_pairs  | 9건
reports   | 5건
summaries | 1건
```

---

### 4.3 reports 컬렉션 전체 목록

```sql
  SELECT
      e.embedding_id,
      MAX(CASE WHEN em.key = 'ticker'         THEN em.string_value END) AS ticker,
      MAX(CASE WHEN em.key = 'raptor_level'   THEN em.int_value    END) AS raptor_level,
      MAX(CASE WHEN em.key = 'published_date' THEN em.string_value END) AS published_date,
      MAX(CASE WHEN em.key = 'source'         THEN em.string_value END) AS source
  FROM collections c
  JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
  JOIN embeddings e ON e.segment_id = s.id
  JOIN embedding_metadata em ON em.id = e.id
  WHERE c.name = 'reports'
  GROUP BY e.embedding_id
  ORDER BY raptor_level, published_date;
  ```

**실행 결과:**
```
l0_005930_55ac...  | 005930 | 0 | 2026-04-07
l0_005930_f61a...  | 005930 | 0 | 2026-04-07
l0_005930_fbf1...  | 005930 | 0 | 2026-04-07
l1_005930_00000    | 005930 | 1 | 2026-04-07
l2_005930_top      | 005930 | 2 | 2026-04-13
```

---

### 4.4 qa_pairs 컬렉션 조회

```sql
SELECT
    e.embedding_id,
    MAX(CASE WHEN em.key = 'ticker'        THEN em.string_value END) AS ticker,
    MAX(CASE WHEN em.key = 'question_type' THEN em.string_value END) AS q_type,
    MAX(CASE WHEN em.key = 'question'      THEN em.string_value END) AS question,
    MAX(CASE WHEN em.key = 'sources'       THEN em.string_value END) AS sources
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
WHERE c.name = 'qa_pairs'
GROUP BY e.embedding_id;
```

> **sources 컬럼 형태:** `['26.04.07_삼성전자_키움증권_....pdf', ...]`  
> RAG 검색(Level 0) 시 참조한 PDF 파일명 목록이 Python 리스트 문자열로 저장된다.  
> `generate_qa.py:118` — `sources = list({r["metadata"].get("source", "") for r in rag_results})`

#### 소스 파일명 포함 + 답변까지 한 번에 조회

```sql
SELECT
    e.embedding_id,
    MAX(CASE WHEN em.key = 'ticker'        THEN em.string_value END) AS ticker,
    MAX(CASE WHEN em.key = 'question_type' THEN em.string_value END) AS q_type,
    MAX(CASE WHEN em.key = 'question'      THEN em.string_value END) AS question,
    MAX(CASE WHEN em.key = 'answer'        THEN em.string_value END) AS answer,
    MAX(CASE WHEN em.key = 'sources'       THEN em.string_value END) AS sources
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
WHERE c.name = 'qa_pairs'
GROUP BY e.embedding_id
ORDER BY ticker, q_type;
```

---

### 4.5 특정 종목(ticker)만 필터링

```sql
SELECT
    e.embedding_id,
    MAX(CASE WHEN em.key = 'raptor_level'   THEN em.int_value    END) AS raptor_level,
    MAX(CASE WHEN em.key = 'published_date' THEN em.string_value END) AS published_date
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
WHERE c.name = 'reports'
GROUP BY e.embedding_id
HAVING MAX(CASE WHEN em.key = 'ticker' THEN em.string_value END) = '005930'
ORDER BY raptor_level;
```

---

### 4.6 원문 텍스트 포함 조회

> **FTS5 컬럼명:** `embedding_fulltext_search_content` 테이블의 텍스트 컬럼은 `c0`이다.  
> (`SELECT name FROM pragma_table_info('embedding_fulltext_search_content')` 로 확인)

```sql
SELECT
    e.embedding_id,
    fts.c0 AS text,
    MAX(CASE WHEN em.key = 'ticker'       THEN em.string_value END) AS ticker,
    MAX(CASE WHEN em.key = 'raptor_level' THEN em.int_value    END) AS raptor_level
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
JOIN embedding_fulltext_search_content fts ON fts.rowid = e.id
WHERE c.name = 'reports'
GROUP BY e.embedding_id
ORDER BY raptor_level;
```

### 4.7 summaries 컬렉션 요약 본문 조회

```sql
SELECT
    e.embedding_id,
    MAX(CASE WHEN em.key = 'ticker'         THEN em.string_value END) AS ticker,
    MAX(CASE WHEN em.key = 'source'         THEN em.string_value END) AS source,
    MAX(CASE WHEN em.key = 'published_date' THEN em.string_value END) AS published_date,
    fts.c0 AS summary_text
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
JOIN embedding_fulltext_search_content fts ON fts.rowid = e.id
WHERE c.name = 'summaries'
GROUP BY e.embedding_id
ORDER BY published_date DESC;
```

특정 종목만 필터링:

```sql
SELECT
    e.embedding_id,
    MAX(CASE WHEN em.key = 'source'         THEN em.string_value END) AS source,
    MAX(CASE WHEN em.key = 'published_date' THEN em.string_value END) AS published_date,
    fts.c0 AS summary_text
FROM collections c
JOIN segments s   ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
JOIN embedding_fulltext_search_content fts ON fts.rowid = e.id
WHERE c.name = 'summaries'
GROUP BY e.embedding_id
HAVING MAX(CASE WHEN em.key = 'ticker' THEN em.string_value END) = '005930'
ORDER BY published_date DESC;
```

---

## 5. 실행 방법

### 방법 A — sqlite3 CLI

```bash
sqlite3 /Users/boon/report_db/chroma.sqlite3

# 프롬프트에서 SQL 직접 입력
sqlite> .headers on
sqlite> .mode column
sqlite> SELECT name FROM collections;
```

### 방법 B — Python sqlite3

```python
import sqlite3

conn = sqlite3.connect('/Users/boon/report_db/chroma.sqlite3')
cur = conn.cursor()
cur.execute("SELECT name FROM collections")
print(cur.fetchall())
conn.close()
```

### 방법 C — DB Browser for SQLite (GUI)

1. [DB Browser for SQLite](https://sqlitebrowser.org) 설치
2. `/Users/boon/report_db/chroma.sqlite3` 파일 열기
3. 테이블 탐색 및 SQL 쿼리 실행 가능

---

## 6. 컬렉션 ID → 이름 빠른 참조

| 컬렉션명 | UUID 앞 8자 | 저장 내용 |
|---------|------------|---------|
| `reports` | `10ca39cf` | L0/L1/L2 청크 (RAPTOR 계층) |
| `summaries` | `2ccd027d` | 리포트별 투자자용 요약 |
| `qa_pairs` | `0a479f0d` | 자기 질문 + 답변 9개/종목 |
