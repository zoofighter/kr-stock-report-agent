from typing import TypedDict, Optional

# 종목 정보
TICKERS = {
    "삼성전자":  "005930",
    "현대차":    "005380",
    "SK하이닉스": "000660",
}

# 파일명에서 종목 필터링할 키워드
COMPANY_KEYWORDS = {
    "005930": "삼성전자",
    "005380": "현대차",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "017670": "SK텔레콤",
}

# 리포트 PDF 저장 경로 (회사명 하위 폴더 구조)
# 예: /Users/boon/report/삼성전자/26.04.07_삼성전자_....pdf
REPORT_DIR = "/Users/boon/report"

# ChromaDB 저장 경로
DB_PATH = "/Users/boon/report_db"


class ResearcherState(TypedDict):
    # 입력
    topic: str           # 예: "삼성전자"
    company_name: str
    ticker: str          # 예: "005930"
    sector: str
    today: str
    report_date: str     # 가장 최근 리포트 발행일 (collect_reports에서 채움)

    # collect_reports 내부
    file_paths: list
    raw_texts: list      # [{"text", "source", "date", "page"}]
    parse_errors: list
    raptor_chunks: list  # Level 0/1/2 포함

    # 출력
    report_chunks: list
    news_chunks: list  # fetch_news 결과
    issues: list       # extract_issues 결과 (카테고리별 핵심 이슈)


class ResearchPackage(TypedDict):
    report_chunks: list
    news_chunks: list
    issues: list


class AnalystState(TypedDict):
    # 입력 (ResearchPackage 언팩)
    topic: str
    company_name: str
    ticker: str
    sector: str
    today: str
    report_date: str
    report_chunks: list
    news_chunks: list
    issues: list

    # ① assess_data
    data_assessment: dict        # {score, warnings, report_count, news_count}

    # ② extract_thesis
    thesis_list: list            # [{"type", "thesis", "evidence", "importance"}]

    # ③ build_toc
    rag_context: str
    toc_draft: list
    toc_iteration: int
    toc_max_retries: int   # build_toc 최대 시도 횟수 (기본값 2)

    # ④ review_toc
    review_feedback: str
    review_approved: bool

    # ⑤ human_toc → 확정 목차
    human_input: str   # main.py가 update_state()로 주입하는 사용자 입력
    toc: list

    # ⑥ plan_sections
    section_plans: list
    global_context_seed: str


class AnalysisPackage(TypedDict):
    toc: list
    thesis_list: list
    section_plans: list
    global_context_seed: str


class WriterState(TypedDict):
    # 입력 (analyst_result에서 전달)
    company_name: str
    ticker: str
    sector: str
    today: str
    report_date: str
    toc: list                  # [{"order", "title", "description"}]
    thesis_list: list          # [{"type", "thesis", "evidence", "importance"}]
    section_plans: list        # Analyst가 생성한 섹션 플랜
    global_context_seed: str

    # write_sections 출력
    written_sections: list     # [{"order", "title", "content"}]
    write_errors: list

    # assemble_report 출력
    report_markdown: str

    # save_report 출력
    output_path: str
