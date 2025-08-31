from flask import Flask, request, jsonify
import requests, random, re, time, asyncio
from bs4 import BeautifulSoup
from urllib.parse import unquote
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

app = Flask(__name__)

# -----------------------------
# User Agents
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
# Proxy Pool
# -----------------------------
PROXIES = [
    # Add your proxy list here
    # Format: "http://user:pass@ip:port" OR "http://ip:port"
    # Example:
    # "http://123.45.67.89:8080",
    # "socks5://user:pass@98.76.54.32:1080"
]

def get_proxy():
    return {"http": random.choice(PROXIES), "https": random.choice(PROXIES)} if PROXIES else None

# -----------------------------
# Playwright Scraper (with retries + proxy)
# -----------------------------
async def scrape_with_playwright(url, retries=3):
    for attempt in range(retries):
        try:
            async with async_playwright() as p:
                proxy = random.choice(PROXIES) if PROXIES else None
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox", "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage", "--disable-gpu"
                    ],
                    proxy={"server": proxy} if proxy else None
                )
                page = await browser.new_page(user_agent=random.choice(USER_AGENTS))
                await stealth_async(page)
                await page.goto(url, timeout=35000, wait_until="domcontentloaded")

                html = await page.content()
                await browser.close()

                return extract_price_image(html)
        except Exception as e:
            if attempt == retries - 1:
                return {"price": f"Error: {str(e)}", "image": None}
            time.sleep(1)

# -----------------------------
# Requests Scraper (with retries + proxy)
# -----------------------------
def scrape_with_requests(url, retries=3):
    for attempt in range(retries):
        try:
            res = requests.get(url, headers=get_headers(), proxies=get_proxy(), timeout=10)
            if res.status_code != 200:
                raise Exception(f"HTTP {res.status_code}")
            return extract_price_image(res.text)
        except Exception as e:
            if attempt == retries - 1:
                return {"price": f"Error: {str(e)}", "image": None}
            time.sleep(1)

# -----------------------------
# Extract Price + Image
# -----------------------------
def extract_price_image(html):
    soup = BeautifulSoup(html, "html.parser")

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
        img = soup.find("img", {"id": "landingImage"}) or soup.find(
            "img", {"class": re.compile(r'(product|main).*image', re.I)})
        if img and img.get("src"):
            img_url = img["src"]

    return {"price": price, "image": img_url if img_url else "Image not found"}

# -----------------------------
# Search Engines
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

BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com", "reddit.com",
    "news", "blog", "review", "howto", "tutorial"
]

BIG_SITES = [
    "amazon.", "flipkart.", "croma.", "ajio.", "myntra.",
    "nykaa.", "snapdeal.", "reliancedigital.", "tatacliq.",
    "paytmmall.", "shopclues.", "ebay.", "aliexpress.", "walmart."
]

def is_shopping_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper Pro (Playwright + Requests + Proxy + Priority) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query required'}), 400

    search_query = f"{query} Buy Online in India"
    results, seen_urls = [], set()
    big_first, others = [], []

    # Collect search results
    for engine_name, engine_url in SEARCH_ENGINES.items():
        try:
            search_url = engine_url.format(query=search_query.replace(' ', '+'))
            res = requests.get(search_url, headers=get_headers(), proxies=get_proxy(), timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.find_all('a', href=True):
                href = a['href']
                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]
                if clean_url in seen_urls or not is_shopping_url(clean_url):
                    continue
                seen_urls.add(clean_url)

                if any(big in clean_url for big in BIG_SITES):
                    big_first.append((clean_url, a.get_text().strip()))
                else:
                    others.append((clean_url, a.get_text().strip()))
        except Exception:
            continue

    # Process big sites first
    for url, text in big_first + others:
        if len(results) >= 20:
            break
        if any(big in url for big in BIG_SITES):
            data = asyncio.run(scrape_with_playwright(url))
        else:
            data = scrape_with_requests(url)

        if data["price"] not in ["Price not found", "Error fetching"]:
            results.append({
                "title": text,
                "url": url,
                "price": data["price"],
                "image": data["image"]
            })

    return jsonify({
        "product": search_query,
        "results": results[:20]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
