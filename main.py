from flask import Flask, request, jsonify
import requests, re, random, time, asyncio
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
from playwright.async_api import async_playwright

app = Flask(__name__)

# ------------------------------------
# Rotating User-Agents + Proxies
# ------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; Redmi Note 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
]

PROXY_POOL = [
    # "http://user:pass@proxy1:port",
    # "http://user:pass@proxy2:port"
]

BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com", "reddit.com",
    "news", "blog", "review", "howto", "tutorial"
]

SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "you": "https://you.com/search?q={query}&tbm=shop",
    "startpage": "https://www.startpage.com/sp/search?q={query}"
}

# ------------------------------------
# Utils
# ------------------------------------
def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

def get_proxy():
    return random.choice(PROXY_POOL) if PROXY_POOL else None

def is_shopping_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)

# ------------------------------------
# Price + Image Extractor
# ------------------------------------
def extract_price_image_from_url(url):
    try:
        res = requests.get(
            url,
            headers=get_headers(),
            proxies={"http": get_proxy(), "https": get_proxy()} if PROXY_POOL else None,
            timeout=12
        )
        soup = BeautifulSoup(res.text, "html.parser")

        # --- PRICE ---
        price_text = soup.get_text()
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        price = "Price not found"
        for pattern in patterns:
            prices = re.findall(pattern, price_text)
            if prices:
                price = prices[0]
                break

        # --- IMAGE ---
        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]

        if not img_url:
            img = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"class": re.compile(r'(product|main).*image', re.I)})
            if img:
                img_url = img.get("src") or img.get("data-src") or img.get("data-image")

        if not img_url:
            for img in soup.find_all("img"):
                candidate = img.get("src") or img.get("data-src")
                if candidate and not candidate.startswith("data:"):
                    img_url = candidate
                    break

        if img_url:
            img_url = urljoin(url, img_url)

        return {"price": price, "image": img_url or "Image not found"}

    except Exception:
        return {"price": "Error fetching", "image": None}

# ------------------------------------
# Playwright (for JS-heavy engines)
# ------------------------------------
async def playwright_fetch(url):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()
        await page.goto(url, timeout=40000)
        content = await page.content()
        await browser.close()
        return BeautifulSoup(content, "html.parser")

# ------------------------------------
# Scraper Logic
# ------------------------------------
def scrape_engine(engine, query):
    try:
        url = SEARCH_ENGINES[engine].format(query=query.replace(" ", "+"))

        # Playwright for JS engines
        if engine in ["you"]:
            soup = asyncio.run(playwright_fetch(url))
        else:
            res = requests.get(url, headers=get_headers(), timeout=12)
            if res.status_code != 200:
                return []
            soup = BeautifulSoup(res.text, "html.parser")

        results, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue

            clean_url = unquote(href.split("&")[0])
            if clean_url in seen or not is_shopping_url(clean_url):
                continue
            seen.add(clean_url)

            if not any(term in a.get_text().lower() for term in ["buy", "price", "shop", "₹", "$"]):
                continue

            data = extract_price_image_from_url(clean_url)
            if data["price"] not in ["Price not found", "Error fetching"]:
                results.append({
                    "title": a.get_text().strip()[:100],
                    "url": clean_url,
                    "price": data["price"],
                    "image": data["image"]
                })

            if len(results) >= 20:
                break

        return results

    except Exception:
        return []

# ------------------------------------
# Flask Endpoints
# ------------------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper Enterprise (Multi-engine + Playwright + Proxies) running!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query required"}), 400

    search_query = f"{query} Buy Online India"
    all_results = []

    for engine in SEARCH_ENGINES:
        results = scrape_engine(engine, search_query)
        if results:
            all_results.extend(results)
        if len(all_results) >= 20:
            break
        time.sleep(random.uniform(1, 2))

    return jsonify({"product": search_query, "results": all_results[:20]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
