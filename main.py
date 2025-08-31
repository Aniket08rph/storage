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
# Playwright helper (async)
# -----------------------------
async def playwright_context():
    """
    Creates a Playwright chromium browser+page with container-friendly flags.
    Call:  p, browser, page = await playwright_context()
    Always close: await browser.close(); await p.stop()
    """
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-web-security",
        ],
    )
    context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
    page = await context.new_page()
    # Slightly more stealthy defaults
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return p, browser, page

# -----------------------------
# Amazon scraping (async)
# -----------------------------
async def scrape_amazon(query: str, max_items: int = 20):
    results = []
    p = browser = page = None
    try:
        p, browser, page = await playwright_context()
        url = f"https://www.amazon.in/s?k={query.replace(' ', '+')}"
        await page.goto(url, timeout=25000)
        await page.wait_for_timeout(2500)

        items = await page.query_selector_all("div.s-result-item[data-asin]")
        for item in items:
            if len(results) >= max_items:
                break
            title_el = await item.query_selector("h2 a span")
            price_whole = await item.query_selector("span.a-price > span.a-offscreen")  # better selector
            image_el = await item.query_selector("img.s-image")
            link_el = await item.query_selector("h2 a")

            if not (title_el and price_whole and image_el and link_el):
                continue

            title = (await title_el.inner_text()).strip()
            price_text = (await price_whole.inner_text()).strip()
            href = await link_el.get_attribute("href")
            image = await image_el.get_attribute("src")

            if not href:
                continue

            results.append({
                "title": title,
                "url": "https://www.amazon.in" + href,
                "price": price_text,
                "image": image
            })
    except Exception as e:
        print("Amazon scrape error:", repr(e))
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if p:
                await p.stop()
        except Exception:
            pass
    return results

# -----------------------------
# Flipkart scraping (async)
# -----------------------------
async def scrape_flipkart(query: str, max_items: int = 20):
    results = []
    p = browser = page = None
    try:
        p, browser, page = await playwright_context()
        url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
        await page.goto(url, timeout=25000)
        await page.wait_for_timeout(2500)

        # Product cards can vary by category; cover common selectors
        cards = await page.query_selector_all("div._1AtVbE")
        for item in cards:
            if len(results) >= max_items:
                break

            title_el = await item.query_selector("div._4rR01T, a.s1Q9rs, a.IRpwTa")
            price_el = await item.query_selector("div._30jeq3")
            image_el = await item.query_selector("img._396cs4, img._2r_T1I")
            link_el = title_el  # same element usually carries href

            if not (title_el and price_el and image_el):
                continue

            title = (await title_el.inner_text()).strip()
            price_text = (await price_el.inner_text()).strip()
            href = await link_el.get_attribute("href") if link_el else None
            image = await image_el.get_attribute("src")

            if not href:
                continue

            if href.startswith("/"):
                href = "https://www.flipkart.com" + href

            results.append({
                "title": title,
                "url": href,
                "price": price_text,
                "image": image
            })
    except Exception as e:
        print("Flipkart scrape error:", repr(e))
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if p:
                await p.stop()
        except Exception:
            pass
    return results

# -----------------------------
# Generic scraper (requests + BS)
# -----------------------------
def scrape_generic(url: str):
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        # Try JSON-LD (structured data)
        price = None
        for ld in soup.find_all("script", type="application/ld+json"):
            m = re.search(r'"price"\s*:\s*"?([0-9.,₹$]+)"?', ld.text)
            if m:
                price = m.group(1)
                break

        # Fallback regex
        if not price:
            text = soup.get_text(" ", strip=True)
            patterns = [r'₹\s?[0-9,]+(?:\.[0-9]{1,2})?', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
            for pattern in patterns:
                prices = re.findall(pattern, text)
                if prices:
                    price = prices[0]
                    break

        # Image
        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img.get("content")
        if not img_url:
            img = soup.find("img", src=True)
            if img:
                img_url = img.get("src")

        title = soup.title.string.strip() if soup.title and soup.title.string else url
        return {
            "title": title,
            "url": url,
            "price": price if price else "Price not found",
            "image": img_url if img_url else "Image not found"
        }
    except Exception as e:
        print("Generic scrape error:", repr(e))
        return {"title": url, "url": url, "price": "Error fetching", "image": None}

# -----------------------------
# Multi-engine search (sync)
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://bing.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "yahoo": "https://search.yahoo.com/search?p={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "searx": "https://searx.org/search?q={query}"
}

def engine_search(query: str, max_urls: int = 20):
    urls = []
    seen = set()

    # Bias engines toward big sites but still allow normal sites
    boosted_query = (
        f"{query} (site:amazon.in OR site:flipkart.com OR site:croma.com "
        f"OR site:reliancedigital.in OR site:tatacliq.com) OR {query} buy online india"
    )

    for engine, base_url in SEARCH_ENGINES.items():
        try:
            search_url = base_url.format(query=boosted_query.replace(" ", "+"))
            res = requests.get(search_url, headers=get_headers(), timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = unquote(a["href"]).split("&")[0]
                if is_shopping_url(href) and href not in seen:
                    seen.add(href)
                    urls.append(href)
                    if len(urls) >= max_urls:
                        return urls
        except Exception as e:
            print(f"{engine} search error:", repr(e))
        time.sleep(random.uniform(0.8, 1.6))
    return urls

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return "🔥 CreativeScraper (Async Playwright + Multi-Engine, 20 results max) is running!"

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"}), 200

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400

    MAX_RESULTS = 20
    results = []

    try:
        # Run Amazon + Flipkart concurrently (async)
        amz, fk = asyncio.run(
            asyncio.wait_for(
                asyncio.gather(
                    scrape_amazon(query, max_items=MAX_RESULTS),
                    scrape_flipkart(query, max_items=MAX_RESULTS),
                ),
                timeout=40,  # overall timeout for both
            )
        )
        results.extend(amz)
        if len(results) < MAX_RESULTS:
            results.extend(fk)

        # Multi-engine fallback if we still need more
        if len(results) < MAX_RESULTS:
            urls = engine_search(query, max_urls=MAX_RESULTS)
            for u in urls:
                if len(results) >= MAX_RESULTS:
                    break
                results.append(scrape_generic(u))

        # Deduplicate by URL while keeping order
        seen = set()
        deduped = []
        for r in results:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                deduped.append(r)

        return jsonify({
            "product": query,
            "results": deduped[:MAX_RESULTS]
        })

    except Exception as e:
        import traceback
        print("[/scrape fatal]", repr(e))
        print(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    # Local run
    app.run(host="0.0.0.0", port=8080)
