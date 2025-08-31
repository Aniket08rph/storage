from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re, random, time, os

app = Flask(__name__)

# ✅ Force Playwright to use persistent cache path
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/root/.cache/ms-playwright"

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

def get_random_ua():
    return random.choice(USER_AGENTS)

def get_random_viewport():
    return {"width": random.randint(1280, 1920), "height": random.randint(720, 1080)}

# -----------------------------
# Extract price + image from HTML
# -----------------------------
def parse_price_image(html):
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
            "img", {"class": re.compile(r'(product|main).*image', re.I)}
        )
        if img and img.get("src"):
            img_url = img["src"]

    if not img_url:
        imgs = soup.find_all("img", src=True)
        if imgs:
            img_url = imgs[0]["src"]

    return {"price": price, "image": img_url if img_url else "Image not found"}


# -----------------------------
# Search engine URLs
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "yahoo": "https://search.yahoo.com/search?p={query}"
}

BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com", "reddit.com",
    "news", "blog", "review", "howto", "tutorial"
]

def is_shopping_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)


# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Optimized Playwright) is running!"

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

    # Proxy pool (optional)
    PROXIES = [
        # {"server": "http://user:pass@proxy1:port"},
    ]
    proxy = random.choice(PROXIES) if PROXIES else None

    try:
        with sync_playwright() as p:
            # 🔹 Launch Chromium safely in Render
            browser = p.chromium.launch(
                headless=True,
                proxy=proxy,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )
            context = browser.new_context(
                user_agent=get_random_ua(),
                viewport=get_random_viewport()
            )

            # Block heavy resources
            def block_resources(route):
                if route.request.resource_type in ["font", "stylesheet", "media", "xhr", "fetch"]:
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", block_resources)

            page = context.new_page()
            stealth_sync(page)

            # Loop search engines
            for engine_name, engine_url in SEARCH_ENGINES.items():
                try:
                    search_url = engine_url.format(query=search_query.replace(" ", "+"))
                    page.goto(search_url, timeout=20000)
                    time.sleep(random.uniform(2, 3))
                    html = page.content()

                    soup = BeautifulSoup(html, "html.parser")
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
                            try:
                                page.goto(clean_url, timeout=20000)
                                time.sleep(random.uniform(2, 4))
                                product_html = page.content()
                                data = parse_price_image(product_html)
                                if data["price"] not in ["Price not found", "Error fetching"]:
                                    results.append({
                                        "title": text,
                                        "url": clean_url,
                                        "price": data["price"],
                                        "image": data["image"]
                                    })
                            except Exception:
                                continue

                        if len(results) >= 10:
                            break
                    if results:
                        break

                    time.sleep(random.uniform(1, 2))
                except Exception:
                    continue

            context.close()
            browser.close()

    except Exception as e:
        # 🔹 Debug hint for Playwright binary issues
        return jsonify({"error": str(e), "hint": "Check PLAYWRIGHT_BROWSERS_PATH and buildCommand in Render"}), 500

    return jsonify({"product": search_query, "results": results[:10]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
