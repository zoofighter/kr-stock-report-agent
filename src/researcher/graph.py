from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import ResearcherState
from src.researcher.collect_reports import collect_reports
from src.researcher.fetch_news import fetch_news
from src.researcher.extract_issues import extract_issues


def build_researcher_graph(checkpointer=None):
    """
    Researcher 서브그래프

    변경 이력:
      구 구조: collect_reports & fetch_news 병렬 → extract_issues → END
      현 구조: collect_reports → fetch_news & extract_issues 병렬 → END

    변경 이유:
      fetch_news가 RAPTOR L2 청크(전체 투자 논지 요약)를 검색어로 활용하려면
      collect_reports 완료 후 report_chunks 상태가 채워진 시점에 실행되어야 함.
      fetch_news와 extract_issues는 서로 독립적이므로 병렬 실행 유지.
    """
    builder = StateGraph(ResearcherState)

    builder.add_node("collect_reports", collect_reports)
    builder.add_node("fetch_news",      fetch_news)
    builder.add_node("extract_issues",  extract_issues)

    # collect_reports 완료 후 fetch_news와 extract_issues 병렬 실행
    builder.add_edge(START,             "collect_reports")
    builder.add_edge("collect_reports", "fetch_news")
    builder.add_edge("collect_reports", "extract_issues")
    builder.add_edge("fetch_news",      END)
    builder.add_edge("extract_issues",  END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp)


researcher_graph = build_researcher_graph()
