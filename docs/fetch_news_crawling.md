# fetch_news.py 에 크롤링 추가 가능 여부 분석

작성일: 2026-04-14

---

## 1. 현재 fetch_news.py 한계

현재 Naver Blog API는 `description` 필드에 **최대 150자 스니펫**만 반환한다.

```python
# 현재 ChromaDB에 저장되는 text
text = f"{item['title']} — {item['summary']}"
# 예: "삼성전자 주가 전망 — 삼성전자의 1분기 실적이 예상을 상회하며...(150자 끊김)"
```

이 스니펫이 RAG 검색 소스가 되므로 **본문 전체 수치·논거가 누락**된다.

---

## 2. 크롤링 추가 가능 여부

### 방법별 현실 평가

| 방법 | 가능 여부 | 권장 | 이유 |
|------|----------|------|------|
| **Naver 검색 페이지 크롤링** | ⚠️ 가능하나 위험 | ❌ | ToS 위반, IP 차단, JS 렌더링 필요 |
| **블로그 포스트 직접 크롤링** | ⚠️ 가능하나 불안정 | ⚠️ | 네이버 블로그 HTML이 iframe 구조라 복잡 |
| **RSS 수집** | ✅ 안전하고 안정적 | ✅ | 공식 RSS, 전체 본문, 추가 라이브러리 불필요 |

→ **RSS 방식으로 fetch_news.py에 추가하는 것이 최적**

---

## 3. Naver 블로그 직접 크롤링의 문제

Naver 블로그는 iframe 이중 구조라 본문이 중첩 URL에 있다.

```
# 블로그 포스트 URL (외부)
https://blog.naver.com/flaneur_jy/224251966159

# 실제 본문 URL (iframe 내부)
https://blog.naver.com/PostView.naver?blogId=flaneur_jy&logNo=224251966159
```

`requests`로 외부 URL을 요청하면 iframe만 나오고 본문이 없다.  
본문을 가져오려면:
- `PostView.naver` URL을 직접 파싱 (가능, 불안정)
- 또는 Playwright/Selenium으로 JS 렌더링 (가능, 복잡)

---

## 4. RSS 방식 추가 설계 (권장)

### RSS URL 형식

```
https://rss.blog.naver.com/{blog_id}.xml

# 예시
blog_id = "flaneur_jy"   (blogger_url에서 추출)
RSS URL = "https://rss.blog.naver.com/flaneur_jy.xml"
```

### fetch_news.py 추가 위치

```
현재 흐름:
  수집 (API 4종) → 중복제거 → 날짜필터 → ChromaDB 저장

추가 흐름:
  수집 (API 4종) → 중복제거 → 날짜필터
    → [NEW] enrich_blog_content (RSS 본문 수집)
    → ChromaDB 저장
```

### 추가 함수: `enrich_blog_content()`

```python
def enrich_blog_content(items: list[dict]) -> list[dict]:
    """
    naver_blog 항목에 대해 RSS로 전체 본문을 수집해 summary를 교체한다.
    RSS 수집 실패 시 기존 API 스니펫을 유지한다.

    처리 흐름:
    1. naver_blog 항목에서 blogger_url 추출
    2. 블로거별 RSS 1회 fetch (같은 블로거 중복 호출 방지)
    3. RSS의 포스트 URL과 item URL이 일치하면 본문으로 교체
    """
    import re

    def strip_html(html: str) -> str:
        return re.sub(r"<[^>]+>", "", html).strip()

    def fetch_rss_posts(blog_id: str) -> dict[str, str]:
        """blog_id → {포스트URL: 본문텍스트}"""
        rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
        try:
            feed = feedparser.parse(rss_url)
            result = {}
            for entry in feed.entries:
                url     = entry.get("link", "")
                content = entry.get("content", [{}])[0].get("value", "") \
                          or entry.get("summary", "")
                text    = strip_html(content)
                if len(text) > 200:
                    result[url] = text
            return result
        except Exception:
            return {}

    # 블로거별 RSS 캐시 (동일 블로거 중복 호출 방지)
    rss_cache: dict[str, dict] = {}

    enriched = []
    for item in items:
        if item.get("source") != "naver_blog":
            enriched.append(item)
            continue

        blogger_url = item.get("blogger_url", "")
        blog_id     = blogger_url.split("/")[-1] if blogger_url else ""
        if not blog_id:
            enriched.append(item)
            continue

        # RSS 캐시 미스 시 fetch
        if blog_id not in rss_cache:
            rss_cache[blog_id] = fetch_rss_posts(blog_id)
            time.sleep(0.1)

        # URL 매칭으로 본문 교체
        post_url     = item.get("url", "")
        full_content = rss_cache[blog_id].get(post_url, "")
        if full_content:
            item = {**item, "summary": full_content[:2000], "content_source": "rss"}
        else:
            item = {**item, "content_source": "api_snippet"}

        enriched.append(item)

    rss_count = sum(1 for i in enriched if i.get("content_source") == "rss")
    print(f"  블로그 본문 RSS 보강: {rss_count}건 / 전체 블로그 {sum(1 for i in enriched if i.get('source')=='naver_blog')}건")
    return enriched
```

### fetch_news() 본문 수정 (3줄 추가)

```python
    # 중복 제거
    deduped = deduplicate(all_items)

    # 최신 90일 이내만 유지
    cutoff  = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    deduped = [i for i in deduped if i.get("published_date", "9999") >= cutoff]

    # ── [추가] 블로그 본문 RSS 보강 ──────────────────────────────
    deduped = enrich_blog_content(deduped)
    # ─────────────────────────────────────────────────────────────

    print(f"  중복 제거 후: {len(deduped)}개")
```

### ChromaDB 저장 text 변경

```python
    # 기존: 스니펫만
    text = f"{item['title']} — {item['summary']}"

    # 변경: RSS 본문이 있으면 전체, 없으면 스니펫
    body = item.get("summary", "")
    text = f"{item['title']}\n\n{body}"    # 줄바꿈으로 구분해 RAG 품질 향상
```

---

## 5. 예상 효과

| 항목 | 변경 전 (API 스니펫) | 변경 후 (RSS 본문) |
|------|--------------------|--------------------|
| 블로그 텍스트 길이 | 150자 | 최대 2,000자 |
| RAG 검색 시 관련 수치 포함 | ❌ 거의 없음 | ✅ 본문 수치·논거 포함 |
| ChromaDB 저장 용량 | 소 | 중 (약 10배) |
| 추가 HTTP 호출 수 | 0 | 블로거 수 (중복 제거, 보통 10~30회) |
| 추가 소요 시간 | 0초 | 약 3~10초 |

---

## 6. 리스크 및 한계

| 리스크 | 내용 | 대응 |
|--------|------|------|
| RSS 없는 블로거 | 일부 블로거는 RSS 비공개 | 기존 스니펫으로 fallback |
| RSS URL 불일치 | RSS의 포스트 URL ≠ API의 포스트 URL | 매칭 실패 → 스니펫 유지 |
| 본문 HTML 잔존 | RSS content에 HTML 태그 포함 | `strip_html()` 처리 |
| 네이버 블로그 전체 비공개 | RSS 없음 | 스킵 |

---

## 7. 결론

| 질문 | 답 |
|------|-----|
| fetch_news에 크롤링 추가 가능한가? | ✅ **RSS 방식으로 가능** |
| Naver 검색 페이지 크롤링은? | ❌ ToS 위험, 추가 이득 없음 |
| 블로그 직접 페이지 크롤링은? | ⚠️ iframe 구조로 복잡, 불안정 |
| 구현 난이도 | ✅ 낮음 (feedparser 이미 설치됨) |
| 기존 코드 변경 | 함수 1개 추가 + fetch_news() 3줄 추가 |
