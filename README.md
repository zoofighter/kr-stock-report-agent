# content_report — 증권 리포트 자동 분석 및 보고서 생성 파이프라인

증권사 PDF 리포트를 수집·분석하고 투자 보고서를 자동으로 생성하는 LangGraph 기반 멀티 에이전트 시스템.

---

## 전체 파이프라인

```
PDF 리포트 (report_source/)
  ↓
Researcher Graph
  collect_reports   PDF → RAPTOR 청킹 (L0/L1/L2) → ChromaDB
  fetch_news        L2 기반 LLM 쿼리 생성 → 뉴스 4종 수집 → ChromaDB
  extract_issues    L1 기반 투자 이슈 추출 → ChromaDB
  ↓
Analyst Graph
  assess_data       데이터 충분성 평가
  extract_thesis    핵심 투자 논지 3~5개 추출
  build_toc         목차 초안 생성
  review_toc        LLM 목차 검토 (최대 N회 반복)
  human_toc ⚡      사람 확인 (HITL interrupt)
  plan_sections     섹션별 작성 가이드 생성
  ↓
Writer Graph
  write_sections    섹션별 본문 작성 (RAG 검색 포함)
  assemble_report   섹션 조립 → Markdown
  save_report       report_output/{ticker}/ 에 저장
```

---

## 주요 특징

- **RAPTOR 계층 청킹**: L0(원문) → L1(중간 요약) → L2(전체 투자 논지) 3단계 저장
- **L2 기반 의미론적 검색어 생성**: LLM이 리포트 논지를 파악해 뉴스 쿼리 자동 생성
- **4종 뉴스 소스**: Naver뉴스 / Google뉴스 / DuckDuckGo / Naver블로그
- **Human-in-the-Loop**: 목차 검토 단계에서 사람이 직접 승인·수정 가능
- **ChromaDB 캐시**: 리포트 청킹은 최초 1회만 처리, 재실행 시 캐시 사용

---

## 디렉토리 구조

```
.
├── main.py                        # 파이프라인 진입점
├── com_list.csv                   # 실행 종목 목록 (company_name, ticker, file_count)
├── organized_companies.csv        # organize_reports.py 출력
├── requirements.txt
├── src/
│   ├── state.py                   # LangGraph State 정의 (ResearcherState/AnalystState/WriterState)
│   ├── models/
│   │   └── llm.py                 # Ollama LLM 설정 (get_llm / get_small_llm)
│   ├── researcher/
│   │   ├── graph.py               # Researcher 그래프 빌드
│   │   ├── collect_reports.py     # PDF 파싱 + RAPTOR 청킹 + ChromaDB 저장
│   │   ├── fetch_news.py          # L2 기반 쿼리 생성 + 뉴스 수집
│   │   ├── extract_issues.py      # L1 기반 투자 이슈 추출
│   │   ├── rag_store.py           # ChromaDB 저장/검색 공통 모듈
│   │   └── organize_reports.py    # PDF를 회사별 폴더로 정리 (독립 스크립트)
│   ├── analyst/
│   │   ├── graph.py               # Analyst 그래프 빌드 (HITL interrupt 포함)
│   │   ├── assess_data.py
│   │   ├── extract_thesis.py
│   │   ├── build_toc.py
│   │   ├── review_toc.py
│   │   ├── human_toc.py
│   │   └── plan_sections.py
│   └── writer/
│       ├── graph.py               # Writer 그래프 빌드
│       ├── write_sections.py      # RAG 기반 섹션 작성
│       ├── assemble_report.py
│       └── save_report.py
└── docs/                          # 설계 문서
```

---

## 데이터 경로

| 경로 | 내용 |
|------|------|
| `/Users/boon/report_source/` | 원본 PDF 리포트 보관 |
| `/Users/boon/report/` | 회사별 정리된 PDF (`organize_reports.py` 출력) |
| `/Users/boon/report_db/` | ChromaDB (reports / news / issues 컬렉션) |
| `/Users/boon/report_output/{ticker}/` | 생성된 보고서 Markdown + 디버그 파일 |

---

## 설치

```bash
pip install -r requirements.txt
```

Ollama 설치 후 필요 모델 pull:

```bash
ollama pull gemma4:26b       # LARGE_MODEL (보고서 작성)
ollama pull gemma4:e4b       # SMALL_MODEL (요약·쿼리 생성)
ollama pull rjmalagon/gte-qwen2-1.5b-instruct-embed-f16  # 임베딩 모델
```

`.env` 파일 (Naver API, 선택):

```
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

---

## 실행

### 기본 실행 (com_list.csv 종목 전체)

```bash
python main.py
```

`com_list.csv`가 없으면 `TARGETS` 리스트(main.py 내)를 사용한다.

### 특정 종목만 실행

```bash
python main.py --ticker 005930
python main.py --ticker 005930 000660
```

### HITL 비활성화 (목차 자동 승인)

```bash
python main.py --no-hitl
```

### TOC 최대 재시도 횟수 설정

```bash
python main.py --toc-retries 3
```

---

## 종목 등록

### 1. PDF 리포트를 회사별 폴더로 정리

```bash
python src/researcher/organize_reports.py 20260101
```

- `/Users/boon/report_source/` 에서 날짜 이후 PDF를 스캔
- 파일명 규칙: `YY.MM.DD_회사명_증권사_제목.pdf`
- KRX에서 종목코드 자동 조회
- 결과: `organized_companies.csv` (company_name, ticker, file_count)

### 2. com_list.csv 편집

`organized_companies.csv` → `com_list.csv` 로 복사 후 실행할 종목만 남긴다.

```csv
company_name,ticker,file_count
삼성전자,005930,13
SK하이닉스,000660,7
```

### 3. state.py COMPANY_KEYWORDS 추가

`collect_reports`가 파일명 필터링에 사용:

```python
COMPANY_KEYWORDS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    ...
}
```

---

## ChromaDB 컬렉션

| 컬렉션 | 내용 | 재시작 후 유지 |
|--------|------|--------------|
| `reports` | L0/L1/L2 RAPTOR 청크 | ✅ |
| `news` | 뉴스 + 블로그 | ✅ |
| `issues` | 투자 이슈 | ✅ |

상태 확인:

```bash
python -c "
import chromadb
c = chromadb.PersistentClient('/Users/boon/report_db')
for col in c.list_collections():
    print(col.name, ':', col.count())
"
```

---

## 출력 파일

```
report_output/
└── {ticker}/
    ├── {date}_{company}_report.md   # 최종 보고서
    └── {date}_{company}_debug.txt   # L2 요약 / 이슈 / 논지 / TOC / 섹션 플랜
```

---

## 관련 문서 (docs/)

| 파일 | 내용 |
|------|------|
| `langgraph_learning.md` | LangGraph 개념 (State/Node/Edge/HITL/RAG) |
| `raptor_design.md` | RAPTOR 계층 청킹 설계 |
| `semantic_news_search.md` | L2 기반 의미론적 뉴스 검색 설계 |
| `data_persistence.md` | ChromaDB vs MemorySaver 저장 방식 |
| `supervisor_pattern.md` | Supervisor 패턴 vs 현재 Sequential 비교 |
| `planner_design.md` | Planner 추가 설계 검토 |
| `skt_verification.md` | SK텔레콤 파이프라인 검증 결과 |
