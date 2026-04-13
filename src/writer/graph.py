from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import WriterState
from src.writer.write_sections import write_sections
from src.writer.assemble_report import assemble_report
from src.writer.save_report import save_report


def build_writer_graph(checkpointer=None):
    """
    Writer 서브그래프
    write_sections → assemble_report → save_report → END
    HITL 없음, 조건 분기 없음 — 선형 파이프라인
    """
    builder = StateGraph(WriterState)

    builder.add_node("write_sections",  write_sections)
    builder.add_node("assemble_report", assemble_report)
    builder.add_node("save_report",     save_report)

    builder.add_edge(START,             "write_sections")
    builder.add_edge("write_sections",  "assemble_report")
    builder.add_edge("assemble_report", "save_report")
    builder.add_edge("save_report",     END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp)


writer_graph = build_writer_graph()
