from langchain_ollama import ChatOllama, OllamaEmbeddings

INFERENCE_MODEL = "gemma4:26b"

SMALL_MODEL     = "gemma4:26b"

EMBEDDING_MODEL = "rjmalagon/gte-qwen2-1.5b-instruct-embed-f16:latest"


def get_llm(model: str = INFERENCE_MODEL, temperature: float = 0.1) -> ChatOllama:
    """추론용 LLM — QA 답변, 질문 생성"""
    return ChatOllama(model=model, temperature=temperature, num_ctx=8192, timeout=120)


def get_small_llm(model: str = SMALL_MODEL) -> ChatOllama:
    """요약·경량 반복 작업용"""
    return ChatOllama(model=model, temperature=0.0, num_ctx=4096, timeout=120)


def get_embeddings(model: str = EMBEDDING_MODEL) -> OllamaEmbeddings:
    """로컬 임베딩 (1536차원)"""
    return OllamaEmbeddings(model=model)
