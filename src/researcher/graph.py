from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import ResearcherState
from src.researcher.collect_reports import collect_reports
from src.researcher.extract_issues import extract_issues


def build_researcher_graph(checkpointer=None):
    """
    Researcher 서브그래프
    START → collect_reports → extract_issues → END
    (fetch_news, advanced_qa는 다음 단계)
    """
    builder = StateGraph(ResearcherState)

    builder.add_node("collect_reports", collect_reports)
    builder.add_node("extract_issues",  extract_issues)

    builder.add_edge(START,             "collect_reports")
    builder.add_edge("collect_reports", "extract_issues")
    builder.add_edge("extract_issues",  END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp)


researcher_graph = build_researcher_graph()
