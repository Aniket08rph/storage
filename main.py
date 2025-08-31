from flask import Flask, request, jsonify
import asyncio, random, re, time
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
from playwright.async_api import async_playwright

app = Flask(__name__)

# -----------------------------
# Rotating User-Agents
# -----------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; Redmi Note 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile Safari/604.1",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
]

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

# -----------------------------
# Block junk domains
# -----------------------------
BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com",
    "reddit.com", "news", "blog", "review", "howto", "tutorial"
]

def is_shopping_url(url: str) -> bool:
    return url and url.startswith("http") and not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
# Playwright helper
# -----------------------------
async def playwright_context():
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
    page = await context.new_page()
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return p, browser, page

# -----------------------------
# Amazon scraping
# -----------------------------
async def scrape_amazon(query: str, max_items: int = 20):
    results = []
    p = browser = None
    try:
        p, browser, page = await playwright_context()
        await page.goto(f"https://www.amazon.in/s?k={query.replace(' ', '+')}", timeout=25000)
        await page.wait_for_timeout(2500)

        items = await page.query_selector_all("div.s-result-item[data-asin]")
        for item in items:
            if len(results) >= max_items:
                break
            title_el = await item.query_selector("h2 a span")
            price_el = await item.query_selector("span.a-price > span.a-offscreen")
            image_el = await item.query_selector("img.s-image")
            link_el = await item.query_selector("h2 a")

            if not (title_el and price_el and image_el and link_el):
                continue

            title = (await title_el.inner_text()).strip()
            price = (await price_el.inner_text()).strip()
            href = await link_el.get_attribute("href")
            img = await image_el.get_attribute("src")

            if href:
                results.append({
                    "title": title,
                    "url": "https://www.amazon.in" + href,
                    "price": price,
                    "image": img
                })
    except Exception as e:
        print("Amazon error:", e)
    finally:
        try:
            if browser: await browser.close()
            if p: await p.stop()
        except: pass
    return results

# -----------------------------
# Flipkart scraping
# -----------------------------
async def scrape_flipkart(query: str, max_items: int = 20):
    results = []
    p = browser = None
    try:
        p, browser, page = await playwright_context()
        await page.goto(f"https://www.flipkart.com/search?q={query.replace(' ', '+')}", timeout=25000)
        await page.wait_for_timeout(2500)

        cards = await page.query_selector_all("div._1AtVbE")
        for item in cards:
            if len(results) >= max_items:
                break
            title_el = await item.query_selector("div._4rR01T, a.s1Q9rs, a.IRpwTa")
            price_el = await item.query_selector("div._30jeq3")
            img_el = await item.query_selector("img._396cs4, img._2r_T1I")

            if not (title_el and price_el and img_el):
                continue

            title = (await title_el.inner_text()).strip()
            price = (await price_el.inner_text()).strip()
            href = await title_el.get_attribute("href") or ""
            if href.startswith("/"):
                href = "https://www.flipkart.com" + href
            img = await img_el.get_attribute("src")

            results.append({
                "title": title,
                "url": href,
                "price": price,
                "image": img
            })
    except Exception as e:
        print("Flipkart error:", e)
    finally:
        try:
            if browser: await browser.close()
            if p: await p.stop()
        except: pass
    return results

# -----------------------------
# Generic scraper
# -----------------------------
def scrape_generic(url: str):
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url

        # JSON-LD or regex price
        price = None
        for ld in soup.find_all("script", type="application/ld+json"):
            m = re.search(r'"price"\s*:\s*"?([0-9.,₹$]+)"?', ld.text)
            if m: 
                price = m.group(1); break
        if not price:
            txt = soup.get_text(" ", strip=True)
            for pat in [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']:
                m = re.findall(pat, txt)
                if m: price = m[0]; break

        img = None
        og = soup.find("meta", property="og:image")
        if og: img = og.get("content")
        if not img:
            i = soup.find("img", src=True)
            if i: img = i.get("src")

        return {"title": title, "url": url, "price": price or "N/A", "image": img}
    except Exception as e:
        print("Generic error:", e)
        return {"title": url, "url": url, "price": "Error", "image": None}

# -----------------------------
# Multi-engine search
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://bing.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}"
}

def engine_search(query: str, max_urls: int = 20):
    urls, seen = [], set()
    boosted = f"{query} (site:amazon.in OR site:flipkart.com OR site:croma.com) OR {query} buy online india"
    for eng, base in SEARCH_ENGINES.items():
        try:
            res = requests.get(base.format(query=boosted.replace(" ", "+")), headers=get_headers(), timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = unquote(a["href"]).split("&")[0]
                if is_shopping_url(href) and href not in seen:
                    seen.add(href); urls.append(href)
                    if len(urls) >= max_urls: return urls
        except Exception as e:
            print(eng, "search error:", e)
        time.sleep(random.uniform(0.5, 1.2))
    return urls

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return "✅ CreativeScraper running (Flask + Playwright + Multi-engine)"

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query: return jsonify({"error": "Query required"}), 400

    MAX = 20
    results = []

    try:
        # Run each scraper safely in its own loop
        amazon_results = asyncio.run(scrape_amazon(query, MAX))
        flipkart_results = asyncio.run(scrape_flipkart(query, MAX))
        results.extend(amazon_results)
        results.extend(flipkart_results)

        # Fallback with engine scraping
        if len(results) < MAX:
            for url in engine_search(query, MAX):
                if len(results) >= MAX: break
                results.append(scrape_generic(url))

        # Dedup by URL
        seen, final = set(), []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"]); final.append(r)

        return jsonify({"product": query, "results": final[:MAX]})
    except Exception as e:
        print("Fatal scrape error:", e)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
