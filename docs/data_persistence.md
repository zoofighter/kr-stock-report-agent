# 데이터 저장 방식 — ChromaDB vs MemorySaver

## 두 가지 저장소

파이프라인은 단계별로 다른 저장소를 사용한다.

---

## ChromaDB (디스크 영구 저장) — Researcher

| 데이터 | 컬렉션 | 재시작 후 유지 |
|--------|--------|---------------|
| report_chunks (L0/L1/L2) | `reports` | ✅ |
| news_chunks | `news` | ✅ |
| issues | `issues` | ✅ |

`collect_reports` 노드는 ChromaDB를 확인해 이미 처리된 종목이면 재처리 없이 캐시에서 불러온다:

```python
existing_count = count_by_ticker("reports", ticker)
if existing_count > 0:
    # 스킵 — ChromaDB에서 불러옴
```

---

## MemorySaver (메모리 임시 저장) — Analyst / Writer

| 데이터 | 저장소 | 재시작 후 유지 |
|--------|--------|---------------|
| thesis_list | MemorySaver (in-memory) | ❌ |
| toc | MemorySaver (in-memory) | ❌ |
| section_plans | MemorySaver (in-memory) | ❌ |
| global_context_seed | MemorySaver (in-memory) | ❌ |

MemorySaver는 LangGraph의 HITL interrupt 재개를 위한 임시 체크포인터다.  
프로세스 종료 시 모든 데이터가 사라진다.

---

## 파이프라인 재실행 시 동작

```
collect_reports → 캐시 히트 → 스킵 (빠름)
fetch_news      → 재수집   (upsert라 중복 없음)
extract_issues  → 재추출   (upsert)
Analyst 전체   → 처음부터 재실행
Writer 전체    → 처음부터 재실행
```

---

## 개선 가능 방향

Analyst 결과(thesis, TOC, section_plans)를 ChromaDB 또는 JSON 파일로 저장하면  
Writer만 단독 재실행이 가능해진다. 현재는 미구현.
