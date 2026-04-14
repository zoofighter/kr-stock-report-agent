# Naver 블로그 데이터 수집 방법 비교 — API vs 웹 검색

작성일: 2026-04-14

---

## 비교 대상

| 방법 | 설명 |
|------|------|
| **A. Naver Blog API** | 공식 Open API (`openapi.naver.com/v1/search/blog`) |
| **B. Naver 검색 크롤링** | `search.naver.com` 검색 결과 페이지 파싱 |
| **C. 개별 블로그 RSS** | 블로거 URL에서 RSS 피드 직접 수집 |

---

## 1. Naver Blog API (현재 사용 중)

### 장점
- **공식 지원**: 안정적, 차단 없음
- **구조화된 데이터**: title, description, link, bloggername, bloggerlink, postdate 바로 제공
- **빠름**: 1회 호출로 100건 반환
- **무료**: 하루 25,000 호출

### 단점
- **본문 없음**: `description`이 최대 150자 스니펫만 제공, 전체 본문 없음
- **검색 결과 한계**: 최대 1,000건 (start 상한값)
- **관련성 낮음**: 키워드 매칭 기반이라 무관한 블로그 혼입
- **최신 편향**: `sort=date` 기준으로만 정렬 가능 (품질 기준 정렬 불가)

### 반환 데이터

```json
{
  "title":       "삼성전자 주가 분석 — 2026년 전망",
  "link":        "https://blog.naver.com/xxx/123",
  "description": "삼성전자의 1분기 실적이 예상을 ...(150자 스니펫)",
  "bloggername": "시그널 필터",
  "bloggerlink": "blog.naver.com/flaneur_jy",
  "postdate":    "20260414"
}
```

**핵심 한계**: description이 스니펫이라 본문 분석, 품질 판단, RAG 활용이 어렵다.

---

## 2. Naver 검색 크롤링

`https://search.naver.com/search.naver?query=삼성전자+주가&where=blog` 페이지를 직접 파싱.

### 장점
- **본문 미리보기 길이**: API보다 긴 스니펫 제공 (300~500자)
- **검색 결과 다양**: 네이버 검색 알고리즘 그대로 활용
- **정렬 옵션**: 관련도순 / 최신순 선택 가능

### 단점
- **비공식**: 네이버 ToS 위반 가능성 (robots.txt 제한)
- **차단 위험**: User-Agent 탐지, IP 차단, Captcha
- **HTML 구조 변경**: 네이버가 HTML 구조 바꾸면 파서 깨짐
- **속도 느림**: 페이지 렌더링 대기 필요 (JS 렌더링 시 Playwright 필요)
- **본문 전체 없음**: 스니펫만 있고 전체 본문은 개별 블로그 재방문 필요

---

## 3. 개별 블로그 RSS 수집

블로거 URL에서 RSS 피드를 직접 수집:  
`https://rss.blog.naver.com/{blog_id}.xml`

### 장점
- **전체 본문 수집 가능**: RSS에 본문 전체 포함 (블로거 설정에 따라 다름)
- **안정적**: 공식 RSS 규격, 차단 없음
- **구조화**: XML 파싱으로 발행일·제목·본문 정확히 추출
- **API 불필요**: Naver 계정 없어도 수집 가능

### 단점
- **블로거 URL 먼저 알아야 함**: 사전에 블로거 목록이 있어야 함 (Bootstrap 문제)
- **최신 글만**: RSS는 보통 최근 20~30개 포스팅만 포함
- **일부 블로거 RSS 비공개**: RSS 피드가 없는 경우도 있음

### RSS URL 형식

```
https://rss.blog.naver.com/{blog_id}.xml

예시:
https://rss.blog.naver.com/flaneur_jy.xml
https://rss.blog.naver.com/kwangpoong.xml
```

---

## 4. 방법별 종합 비교

| 항목 | A. Naver API | B. 검색 크롤링 | C. RSS 수집 |
|------|-------------|--------------|------------|
| 합법성·안정성 | ✅ 공식 API | ⚠️ ToS 위험 | ✅ 공개 규격 |
| 본문 전체 | ❌ 스니펫 150자 | ❌ 스니펫 300자 | ✅ 전체 본문 |
| 발견(Discovery) | ✅ 키워드 검색 | ✅ 키워드 검색 | ❌ URL 사전 필요 |
| 수집 속도 | ✅ 빠름 | ⚠️ 보통 | ✅ 빠름 |
| 차단 위험 | ✅ 없음 | ⚠️ 있음 | ✅ 없음 |
| RAG 품질 | ⚠️ 낮음 (짧음) | ⚠️ 낮음 (짧음) | ✅ 높음 |
| 구현 복잡도 | ✅ 낮음 | ⚠️ 높음 | ✅ 낮음 |

---

## 5. 권장 조합 — A + C 2단계 방식

단독으로는 어느 방법도 완전하지 않다.  
**API로 블로거를 발견하고, RSS로 본문을 수집**하는 2단계 방식이 최적이다.

```
[ 1단계: 발견 — Naver Blog API ]
쿼리 10개 → 블로거 500명 후보 수집 → 선별 조건 적용 → 중요 블로거 200명 확정

[ 2단계: 본문 수집 — RSS ]
200명 × RSS 피드 = 최근 포스팅 4,000건 (1인당 20건)
→ 전체 본문 ChromaDB 저장 → RAG 검색 활용
```

### 구현 흐름

```
generate_queries (LLM)
  ↓
collect_bloggers (Naver API)       ← 블로거 발견
  ↓
filter_bloggers (선별 조건)
  ↓
fetch_rss (RSS feedparser)         ← 본문 수집
  ↓
upsert_chunks (ChromaDB)           ← 저장
```

### RSS 수집 코드 스케치

```python
import feedparser

def fetch_blogger_rss(blogger_url: str) -> list[dict]:
    """
    blogger_url: 'blog.naver.com/flaneur_jy'
    RSS URL:     'https://rss.blog.naver.com/flaneur_jy.xml'
    """
    blog_id  = blogger_url.split("/")[-1]
    rss_url  = f"https://rss.blog.naver.com/{blog_id}.xml"
    feed     = feedparser.parse(rss_url)

    posts = []
    for entry in feed.entries:
        content = entry.get("summary", "")          # 본문 전체 (HTML 포함)
        text    = strip_html(content)               # HTML 태그 제거
        if len(text) < 200:
            continue
        posts.append({
            "title":    entry.get("title", ""),
            "url":      entry.get("link", ""),
            "text":     text,
            "date":     entry.get("published", ""),
            "blogger":  blog_id,
        })
    return posts
```

---

## 6. 결론

| 질문 | 답 |
|------|-----|
| 블로거 **발견**에는? | **Naver API** (빠르고 안전) |
| 블로그 **본문 수집**에는? | **RSS** (전체 본문, 안정적) |
| 검색 크롤링은? | **사용 안 함** (ToS 위험, 복잡도 대비 이득 없음) |
| 최종 권장 | **API → RSS 2단계** |

현재 파이프라인은 API만 사용해 스니펫(150자)으로 RAG를 구성하고 있다.  
RSS를 추가하면 블로그 전체 본문이 ChromaDB에 들어가 RAG 품질이 크게 향상된다.
