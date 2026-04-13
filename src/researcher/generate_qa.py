import json

from src.models.llm import get_llm, get_small_llm
from src.researcher.rag_store import upsert_chunks, search
from src.state import ResearcherState


def generate_summary(report_chunks: list[dict], ticker: str, llm) -> list[str]:
    """
    Level 1 청크(중간 요약)를 소스 파일별로 그룹화하여 최종 요약 생성
    생성된 요약은 summaries 컬렉션에 저장
    """
    l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 1]
    if not l1_chunks:
        l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 0][:10]

    # 소스 파일별 그룹화
    by_source: dict[str, list] = {}
    for c in l1_chunks:
        src = c["metadata"].get("source", "unknown")
        by_source.setdefault(src, []).append(c)

    summaries = []
    for source, chunks in by_source.items():
        combined = "\n\n".join(c["text"] for c in chunks[:5])
        pub_date  = chunks[0]["metadata"].get("published_date", "")

        prompt = (
            f"증권사 리포트 요약을 읽고 투자자용 최종 요약을 작성하세요.\n\n"
            f"[리포트: {source}]\n{combined}\n\n"
            "요약 형식:\n"
            "- 핵심 투자 포인트: (1~2문장)\n"
            "- 목표주가/투자의견: (수치 포함)\n"
            "- 주요 리스크: (1문장)"
        )
        summary_text = llm.invoke(prompt).content.strip()
        summaries.append(summary_text)

        # summaries 컬렉션 저장
        sum_id = f"sum_{ticker}_{source[:30].replace(' ', '_')}"
        upsert_chunks("summaries", [{
            "id":   sum_id,
            "text": summary_text,
            "metadata": {
                "ticker":         ticker,
                "source":         source,
                "published_date": pub_date,
                "raptor_level":   1,
            },
        }])

    return summaries


def generate_questions(
    summaries: list[str],
    ticker: str,
    company_name: str,
    llm,
) -> list[dict]:
    """
    요약 기반 질문 9개 생성
    - 사실확인형 3개 / 판단근거형 3개 / 리스크형 3개
    """
    combined = "\n\n---\n\n".join(summaries)

    prompt = (
        f"당신은 투자 리서치 전문가입니다.\n"
        f"아래 {company_name}({ticker}) 리포트 요약을 읽고\n"
        "투자 판단에 중요한 질문을 9개 생성하세요.\n\n"
        f"[요약]\n{combined}\n\n"
        "조건:\n"
        "- 사실확인형 3개: 구체적 수치나 날짜를 확인하는 질문\n"
        "- 판단근거형 3개: 왜 그런 판단을 내렸는지 이유를 묻는 질문\n"
        "- 리스크형 3개: 하방 리스크와 주의사항을 묻는 질문\n"
        "- 각 질문은 단독으로 의미가 통할 것\n"
        "- 중복 없을 것\n\n"
        "출력 형식 (JSON 배열만, 다른 텍스트 없이):\n"
        '[\n  {"type": "사실확인형", "question": "..."},\n'
        '  {"type": "판단근거형", "question": "..."},\n'
        '  ...\n]'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        questions = json.loads(response[start:end])
    except Exception:
        # 파싱 실패 시 기본 질문
        questions = [
            {"type": "사실확인형", "question": f"{company_name}의 최근 분기 영업이익은?"},
            {"type": "사실확인형", "question": f"{company_name}의 목표주가는?"},
            {"type": "사실확인형", "question": f"{company_name}의 투자의견은?"},
            {"type": "판단근거형", "question": f"{company_name} 매수 의견의 핵심 근거는?"},
            {"type": "판단근거형", "question": f"{company_name}의 성장 동력은 무엇인가?"},
            {"type": "판단근거형", "question": f"{company_name}의 경쟁 우위는?"},
            {"type": "리스크형",   "question": f"{company_name}의 주요 하방 리스크는?"},
            {"type": "리스크형",   "question": f"{company_name}의 업황 리스크는?"},
            {"type": "리스크형",   "question": f"{company_name}의 실적 하락 요인은?"},
        ]

    return questions


def answer_question(question: dict, ticker: str, llm) -> dict:
    """RAG 검색으로 질문에 답변 생성"""
    rag_results = search(
        collection_name="reports",
        query=question["question"],
        ticker=ticker,
        top_k=3,
        level=0,  # 수치 정확성을 위해 원문 청크 사용
    )

    context = "\n\n".join(r["text"] for r in rag_results)
    sources = list({r["metadata"].get("source", "") for r in rag_results})

    prompt = (
        "아래 컨텍스트를 바탕으로 질문에 답변하세요.\n"
        "컨텍스트에 없는 내용은 추측하지 말고 '정보 없음'으로 답하세요.\n\n"
        f"[질문]\n{question['question']}\n\n"
        f"[컨텍스트]\n{context}\n\n"
        "답변 (2~3문장, 수치 포함):"
    )

    answer = llm.invoke(prompt).content.strip()

    return {
        **question,
        "answer":  answer,
        "sources": sources,
        "ticker":  ticker,
    }


def generate_qa(state: ResearcherState) -> dict:
    """
    Researcher 노드: generate_qa
    1. 리포트 요약 생성 → summaries 컬렉션 저장
    2. 핵심 질문 9개 생성
    3. RAG 검색으로 답변 생성 → qa_pairs 컬렉션 저장
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    report_chunks = state["report_chunks"]

    print(f"[generate_qa] {company_name} ({ticker}) 시작")

    llm       = get_llm()
    small_llm = get_small_llm()

    # 1. 요약 생성
    summaries = generate_summary(report_chunks, ticker, small_llm)
    print(f"  요약 생성: {len(summaries)}개")

    if not summaries:
        print("  [WARN] 요약 없음 — QA 건너뜀")
        return {"summaries": [], "qa_pairs": [], "qa_draft": []}

    # 2. 질문 생성
    questions = generate_questions(summaries, ticker, company_name, small_llm)
    print(f"  질문 생성: {len(questions)}개")

    # 3. 답변 생성 및 저장
    qa_pairs = []
    for q in questions:
        qa = answer_question(q, ticker, llm)
        qa_pairs.append(qa)

        qa_id = f"qa_{ticker}_{abs(hash(q['question'])) % 0xFFFF:04x}"
        upsert_chunks("qa_pairs", [{
            "id":   qa_id,
            "text": f"Q: {qa['question']}\nA: {qa['answer']}",
            "metadata": {
                "ticker":         ticker,
                "question_type":  qa["type"],
                "question":       qa["question"],
                "answer":         qa["answer"],
                "sources":        str(qa["sources"]),
                "published_date": state.get("report_date", ""),
            },
        }])

    print(f"  QA 저장: {len(qa_pairs)}개")

    return {
        "summaries": summaries,
        "qa_pairs":  qa_pairs,
        "qa_draft":  qa_pairs,
    }
