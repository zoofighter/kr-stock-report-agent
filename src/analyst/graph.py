from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import AnalystState
from src.analyst.assess_data import assess_data
from src.analyst.extract_thesis import extract_thesis
from src.analyst.build_toc import build_toc
from src.analyst.review_toc import review_toc
from src.analyst.human_toc import human_toc
from src.analyst.plan_sections import plan_sections


def _route_after_build(state: AnalystState) -> str:
    """build_toc 직후 — 최대 횟수 도달 시 바로 human_toc으로 이동 (review 생략)."""
    toc_iteration   = state.get("toc_iteration", 1)
    toc_max_retries = state.get("toc_max_retries", 2)

    if toc_iteration >= toc_max_retries:
        print(f"  [router] 최대 {toc_max_retries}회 도달 — review 생략, 강제 승인")
        return "human_toc"
    return "review_toc"


def _route_review(state: AnalystState) -> str:
    """review_toc 결과에 따라 다음 노드 결정."""
    if state.get("review_approved"):
        return "human_toc"
    return "build_toc"


def _route_human(state: AnalystState) -> str:
    """human_toc 결과에 따라 다음 노드 결정"""
    if state.get("review_approved") and state.get("toc"):
        return "plan_sections"
    return "build_toc"   # 수정 요청


def build_analyst_graph(checkpointer=None):
    """
    Analyst 서브그래프
    assess_data → extract_thesis → build_toc → review_toc
      → (승인) human_toc → plan_sections → END
      → (재작성) build_toc (최대 3회)
    """
    builder = StateGraph(AnalystState)

    builder.add_node("assess_data",    assess_data)
    builder.add_node("extract_thesis", extract_thesis)
    builder.add_node("build_toc",      build_toc)
    builder.add_node("review_toc",     review_toc)
    builder.add_node("human_toc",      human_toc)
    builder.add_node("plan_sections",  plan_sections)

    builder.add_edge(START,            "assess_data")
    builder.add_edge("assess_data",    "extract_thesis")
    builder.add_edge("extract_thesis", "build_toc")

    # build_toc 직후: 최대 횟수 도달 시 review 생략하고 바로 human_toc
    builder.add_conditional_edges("build_toc", _route_after_build,
                                  {"review_toc": "review_toc", "human_toc": "human_toc"})

    builder.add_conditional_edges("review_toc", _route_review,
                                  {"human_toc": "human_toc", "build_toc": "build_toc"})
    builder.add_conditional_edges("human_toc", _route_human,
                                  {"plan_sections": "plan_sections", "build_toc": "build_toc"})

    builder.add_edge("plan_sections", END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp, interrupt_before=["human_toc"])


analyst_graph = build_analyst_graph()
