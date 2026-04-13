import re
import hashlib
from pathlib import Path
from datetime import datetime

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.models.llm import get_small_llm
from src.researcher.rag_store import upsert_chunks
from src.state import ResearcherState, REPORT_DIR, COMPANY_KEYWORDS

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100
CLUSTER_SIZE  = 5   # Level 1 요약: 청크 몇 개씩 묶을지


def extract_date_from_filename(filename: str) -> str:
    """
    파일명 패턴: YY.MM.DD_종목명_...
    예: 26.04.08_삼성전자_키움증권_...pdf → 2026-04-08
    """
    match = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', filename)
    if match:
        yy, mm, dd = match.group(1), match.group(2), match.group(3)
        return f"20{yy}-{mm}-{dd}"
    return datetime.today().strftime("%Y-%m-%d")


def load_reports(ticker: str) -> list[dict]:
    """
    /Users/boon/report/ 에서 종목명이 파일명에 포함된 PDF만 로드
    파일명 예: 26.04.08_삼성전자_키움증권_너무 좋아도 걱정.pdf
    """
    company_keyword = COMPANY_KEYWORDS[ticker]
    report_path = Path(REPORT_DIR)
    raw_docs = []

    pdf_files = sorted(report_path.glob("*.pdf"))
    matched = [p for p in pdf_files if company_keyword in p.name]

    print(f"  [{company_keyword}] 매칭 파일: {len(matched)}개")

    for pdf_path in matched:
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            pub_date = extract_date_from_filename(pdf_path.name)

            for page in pages:
                text = page.page_content.strip()
                if not text:
                    continue
                raw_docs.append({
                    "text":           text,
                    "source":         pdf_path.name,
                    "published_date": pub_date,
                    "page":           page.metadata.get("page", 0),
                    "ticker":         ticker,
                })
        except Exception as e:
            print(f"  [WARN] {pdf_path.name} 파싱 실패: {e}")

    return raw_docs


def make_chunks(raw_docs: list[dict], ticker: str) -> list[dict]:
    """Level 0: 원문 청크 생성"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = []
    for doc in raw_docs:
        parts = splitter.split_text(doc["text"])
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            chunk_id = hashlib.md5(
                f"{doc['source']}_{doc['page']}_{i}_{part[:20]}".encode()
            ).hexdigest()[:16]

            chunks.append({
                "id":   f"l0_{ticker}_{chunk_id}",
                "text": part,
                "metadata": {
                    "ticker":             ticker,
                    "source":             doc["source"],
                    "published_date":     doc["published_date"],
                    "page":               doc["page"],
                    "raptor_level":       0,
                    "source_reliability": 1.0,
                },
            })
    return chunks


def summarize_cluster(texts: list[str], llm) -> str:
    """청크 묶음 → Level 1 중간 요약"""
    joined = "\n\n".join(texts)
    prompt = (
        "다음 증권사 리포트 내용을 3~5문장으로 요약하세요.\n"
        "핵심 수치(영업이익, 목표주가, 성장률 등)를 반드시 포함하세요.\n\n"
        f"[내용]\n{joined}\n\n요약:"
    )
    return llm.invoke(prompt).content.strip()


def summarize_all(level1_texts: list[str], llm) -> str:
    """Level 1 요약들 → Level 2 전체 요약"""
    joined = "\n\n".join(level1_texts)
    prompt = (
        "다음 리포트 요약들을 종합하여 전체 투자 논지를 2~3문장으로 작성하세요.\n\n"
        f"[요약 목록]\n{joined}\n\n전체 요약:"
    )
    return llm.invoke(prompt).content.strip()


def build_raptor(chunks: list[dict], ticker: str) -> tuple[list[dict], list[dict]]:
    """
    RAPTOR 계층 구성
    Returns: (level1_chunks, level2_chunks)
    """
    llm = get_small_llm()
    level1_chunks, level1_texts = [], []

    l0_texts = [c["text"] for c in chunks]
    for i in range(0, len(l0_texts), CLUSTER_SIZE):
        cluster = l0_texts[i: i + CLUSTER_SIZE]
        if not cluster:
            continue

        summary = summarize_cluster(cluster, llm)
        child_ids = [chunks[j]["id"] for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))]

        # Level 1의 published_date = 하위 청크 중 최신 날짜
        latest_date = max(
            chunks[j]["metadata"]["published_date"]
            for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))
        )

        level1_chunks.append({
            "id":   f"l1_{ticker}_{i:05d}",
            "text": summary,
            "metadata": {
                "ticker":             ticker,
                "raptor_level":       1,
                "child_ids":          str(child_ids),
                "source_reliability": 1.0,
                "published_date":     latest_date,
            },
        })
        level1_texts.append(summary)

    level2_chunks = []
    if level1_texts:
        top_summary = summarize_all(level1_texts, llm)
        level2_chunks.append({
            "id":   f"l2_{ticker}_top",
            "text": top_summary,
            "metadata": {
                "ticker":             ticker,
                "raptor_level":       2,
                "child_ids":          str([c["id"] for c in level1_chunks]),
                "source_reliability": 1.0,
                "published_date":     datetime.today().strftime("%Y-%m-%d"),
            },
        })

    return level1_chunks, level2_chunks


def collect_reports(state: ResearcherState) -> dict:
    """
    Researcher 노드: collect_reports
    1. PDF 로드 (종목명 필터)
    2. Level 0 청크 생성
    3. RAPTOR Level 1/2 생성
    4. ChromaDB 저장
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    print(f"[collect_reports] {company_name} ({ticker}) 시작")

    raw_docs = load_reports(ticker)
    if not raw_docs:
        print(f"  [WARN] {ticker}: 리포트 파일 없음")
        return {"parse_errors": [f"{ticker}: 리포트 없음"], "report_chunks": [],
                "raptor_chunks": [], "raw_texts": [], "report_date": ""}

    # Level 0
    l0_chunks = make_chunks(raw_docs, ticker)
    print(f"  Level 0 청크: {len(l0_chunks)}개")

    # RAPTOR Level 1/2
    l1_chunks, l2_chunks = build_raptor(l0_chunks, ticker)
    print(f"  Level 1 요약: {len(l1_chunks)}개 / Level 2 요약: {len(l2_chunks)}개")

    all_chunks = l0_chunks + l1_chunks + l2_chunks

    # ChromaDB 저장
    saved = upsert_chunks("reports", all_chunks)
    print(f"  RAG 저장 완료: {saved}개 → {state['ticker']} @ /Users/boon/report_db")

    # 가장 최신 리포트 날짜
    latest_date = max(c["metadata"]["published_date"] for c in l0_chunks)

    return {
        "report_chunks": all_chunks,
        "raptor_chunks": all_chunks,
        "report_date":   latest_date,
        "raw_texts":     raw_docs,
        "parse_errors":  [],
    }
