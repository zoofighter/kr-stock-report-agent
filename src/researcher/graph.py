from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import ResearcherState
from src.researcher.collect_reports import collect_reports
from src.researcher.fetch_news import fetch_news
from src.researcher.extract_issues import extract_issues


def build_researcher_graph(checkpointer=None):
    """
    Researcher 서브그래프
    collect_reports & fetch_news 병렬 실행 → extract_issues → END
    """
    builder = StateGraph(ResearcherState)

    builder.add_node("collect_reports", collect_reports)
    builder.add_node("fetch_news",      fetch_news)
    builder.add_node("extract_issues",  extract_issues)

    # collect_reports와 fetch_news 병렬 실행
    builder.add_edge(START,             "collect_reports")
    builder.add_edge(START,             "fetch_news")

    # 둘 다 완료되면 extract_issues 실행
    builder.add_edge("collect_reports", "extract_issues")
    builder.add_edge("fetch_news",      "extract_issues")
    builder.add_edge("extract_issues",  END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp)


researcher_graph = build_researcher_graph()
