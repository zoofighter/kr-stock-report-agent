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
    issues: list   # extract_issues 결과 (카테고리별 핵심 이슈)


class ResearchPackage(TypedDict):
    report_chunks: list
    issues: list
    # news_chunks, advanced_qa_pairs는 다음 단계
