from pathlib import Path

from src.state import WriterState

OUTPUT_BASE = "/Users/boon/report_output"


def save_report(state: WriterState) -> dict:
    """
    Writer 노드: save_report
    report_markdown을 마크다운 파일로 저장합니다.
    경로: /Users/boon/report_output/{ticker}/YYYY-MM-DD_{company_name}_report.md
    """
    ticker          = state["ticker"]
    company_name    = state["company_name"]
    today           = state["today"]
    report_markdown = state.get("report_markdown", "")

    output_dir  = Path(OUTPUT_BASE) / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    filename    = f"{today}_{company_name}_report.md"
    output_path = output_dir / filename

    output_path.write_text(report_markdown, encoding="utf-8")

    size_kb = output_path.stat().st_size / 1024
    print(f"[save_report] 저장 완료: {output_path}  ({size_kb:.1f} KB)")

    return {"output_path": str(output_path)}
