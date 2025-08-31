from flask import Flask, request, jsonify
import requests, re, random, time, threading
from bs4 import BeautifulSoup
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

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
# Proxy Pool (with validation)
# -----------------------------
PROXIES = []

def fetch_proxies():
    global PROXIES
    try:
        res = requests.get("https://free-proxy-list.net/", timeout=10, headers=get_headers())
        soup = BeautifulSoup(res.text, "html.parser")
        proxies = []
        for row in soup.select("table tbody tr")[:50]:
            cols = row.find_all("td")
            ip, port, https = cols[0].text, cols[1].text, cols[6].text
            if https == "yes":
                proxy = f"http://{ip}:{port}"
                try:
                    test = requests.get("https://httpbin.org/ip", proxies={"http": proxy, "https": proxy}, timeout=5)
                    if test.status_code == 200:
                        proxies.append(proxy)
                except:
                    continue
        if proxies:
            PROXIES = proxies
            print(f"[Proxy] Validated {len(PROXIES)} proxies")
    except Exception as e:
        print(f"[Proxy] Failed to fetch proxies: {e}")

def get_proxy():
    if not PROXIES:
        fetch_proxies()
    return random.choice(PROXIES) if PROXIES else None

# Refresh proxy pool every 10 min
def refresh_proxy_pool():
    while True:
        fetch_proxies()
        time.sleep(600)

threading.Thread(target=refresh_proxy_pool, daemon=True).start()

# -----------------------------
# Playwright lazy setup
# -----------------------------
playwright = None
browser = None

def get_browser():
    global playwright, browser
    if not playwright or not browser:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage"
            ]
        )
    return browser

@app.teardown_appcontext
def close_browser(exception=None):
    global playwright, browser
    if browser:
        browser.close()
        browser = None
    if playwright:
        playwright.stop()
        playwright = None

# -----------------------------
# Extract price + image
# -----------------------------
def extract_price_image_with_playwright(url):
    try:
        browser = get_browser()
        proxy = get_proxy()
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            proxy={"server": proxy} if proxy else None
        )
        page = context.new_page()
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
        soup = BeautifulSoup(page.content(), "html.parser")
        context.close()

        # PRICE
        price_text = soup.get_text()
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        price = next((m for p in patterns for m in re.findall(p, price_text)), "Price not found")

        # IMAGE
        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]
        if not img_url:
            img = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"class": re.compile(r'(product|main).*image', re.I)})
            if img and img.get("src"):
                img_url = img["src"]
        if not img_url and soup.find_all("img", src=True):
            img_url = soup.find_all("img", src=True)[0]["src"]

        return {"price": price, "image": img_url or "Image not found"}

    except Exception as e:
        return {"price": "Error fetching", "image": None, "error": str(e)}

def extract_price_image_requests(url):
    try:
        proxy = get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        res = requests.get(url, headers=get_headers(), timeout=12, proxies=proxies)
        soup = BeautifulSoup(res.text, "html.parser")

        price_text = soup.get_text()
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        price = next((m for p in patterns for m in re.findall(p, price_text)), "Price not found")

        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]
        if not img_url:
            img = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"class": re.compile(r'(product|main).*image', re.I)})
            if img and img.get("src"):
                img_url = img["src"]
        if not img_url and soup.find_all("img", src=True):
            img_url = soup.find_all("img", src=True)[0]["src"]

        return {"price": price, "image": img_url or "Image not found"}

    except Exception:
        return {"price": "Error fetching", "image": None}

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

BLOCKED_DOMAINS = ["wikipedia.org", "quora.com", "youtube.com", "reddit.com", "news", "blog", "review", "howto", "tutorial"]

def is_shopping_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Playwright + Requests + Proxy Validation) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query required"}), 400

    search_query = f"{query} Buy Online in India"
    results, seen_urls = [], set()

    for engine_name, engine_url in SEARCH_ENGINES.items():
        try:
            search_url = engine_url.format(query=search_query.replace(" ", "+"))
            proxy = get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            res = requests.get(search_url, headers=get_headers(), timeout=12, proxies=proxies)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]
                text = a.get_text().strip()

                if clean_url in seen_urls or not is_shopping_url(clean_url):
                    continue
                seen_urls.add(clean_url)

                if any(term in text.lower() for term in ["₹", "price", "$", "rs", "buy"]):
                    data = extract_price_image_requests(clean_url)
                    if data["price"] in ["Price not found", "Error fetching"]:
                        data = extract_price_image_with_playwright(clean_url)

                    if data["price"] not in ["Price not found", "Error fetching"]:
                        results.append({
                            "title": text,
                            "url": clean_url,
                            "price": data["price"],
                            "image": data["image"]
                        })

                if len(results) >= 10:
                    break

            if results:
                break

            time.sleep(random.uniform(1, 2))

        except Exception as e:
            print(f"[Scrape error] {e}")
            continue

    return jsonify({"product": search_query, "results": results[:10]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
