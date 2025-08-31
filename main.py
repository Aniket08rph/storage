from flask import Flask, request, jsonify
import requests, re, random, time
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
# Block junk domains
# -----------------------------
BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com",
    "reddit.com", "news", "blog", "review", "howto", "tutorial"
]

def is_shopping_url(url):
    return url.startswith("http") and not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
# Playwright helper
# -----------------------------
def playwright_session():
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()
    page.set_user_agent(random.choice(USER_AGENTS))
    return p, browser, page

# -----------------------------
# Amazon scraping
# -----------------------------
def scrape_amazon(query):
    results = []
    p, browser, page = playwright_session()
    try:
        url = f"https://www.amazon.in/s?k={query.replace(' ', '+')}"
        page.goto(url, timeout=20000)
        page.wait_for_timeout(3000)

        items = page.query_selector_all("div.s-result-item[data-asin]")[:20]  # increased to 20
        for item in items:
            title = item.query_selector("h2 a span")
            price = item.query_selector("span.a-price-whole")
            image = item.query_selector("img.s-image")

            if title and price and image:
                results.append({
                    "title": title.inner_text().strip(),
                    "url": "https://www.amazon.in" + item.query_selector("h2 a").get_attribute("href"),
                    "price": "₹" + price.inner_text().strip(),
                    "image": image.get_attribute("src")
                })
    except Exception as e:
        print("Amazon scrape error:", e)
    finally:
        browser.close()
        p.stop()
    return results

# -----------------------------
# Flipkart scraping
# -----------------------------
def scrape_flipkart(query):
    results = []
    p, browser, page = playwright_session()
    try:
        url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
        page.goto(url, timeout=20000)
        page.wait_for_timeout(3000)

        items = page.query_selector_all("div._1AtVbE")[:20]  # increased to 20
        for item in items:
            title = item.query_selector("a.s1Q9rs, a.IRpwTa, div._4rR01T")
            price = item.query_selector("div._30jeq3")
            image = item.query_selector("img._396cs4, img._2r_T1I")

            if title and price and image:
                results.append({
                    "title": title.inner_text().strip(),
                    "url": "https://www.flipkart.com" + (title.get_attribute("href") or ""),
                    "price": price.inner_text().strip(),
                    "image": image.get_attribute("src")
                })
    except Exception as e:
        print("Flipkart scrape error:", e)
    finally:
        browser.close()
        p.stop()
    return results

# -----------------------------
# Fallback generic scraper
# -----------------------------
def scrape_generic(url):
    try:
        res = requests.get(url, headers=get_headers(), timeout=8)
        soup = BeautifulSoup(res.text, "html.parser")

        price = None
        ld_json = soup.find("script", type="application/ld+json")
        if ld_json:
            m = re.search(r'"price"\s*:\s*"?([0-9.,₹$]+)"?', ld_json.text)
            if m:
                price = m.group(1)

        if not price:
            text = soup.get_text()
            patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
            for pattern in patterns:
                prices = re.findall(pattern, text)
                if prices:
                    price = prices[0]
                    break

        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]
        if not img_url:
            img = soup.find("img")
            if img and img.get("src"):
                img_url = img["src"]

        return {
            "title": soup.title.string if soup.title else url,
            "url": url,
            "price": price if price else "Price not found",
            "image": img_url if img_url else "Image not found"
        }
    except Exception as e:
        print("Generic scrape error:", e)
        return {"title": url, "url": url, "price": "Error fetching", "image": None}

# -----------------------------
# Multi-engine search
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

def engine_search(query):
    urls = set()
    boosted_query = f"{query} site:amazon.in OR site:flipkart.com OR site:croma.com OR site:reliancedigital.in OR site:tatacliq.com"

    for engine, base_url in SEARCH_ENGINES.items():
        try:
            search_url = base_url.format(query=boosted_query.replace(" ", "+"))
            res = requests.get(search_url, headers=get_headers(), timeout=8)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = unquote(a["href"])
                if is_shopping_url(href):
                    urls.add(href.split("&")[0])
        except Exception as e:
            print(f"{engine} search error:", e)
        time.sleep(random.uniform(1, 2))
    return list(urls)[:20]  # increased to 20

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Amazon + Flipkart + Multi-Engine, 20 results max) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query required"}), 400

    results = []

    # 1. Amazon
    results.extend(scrape_amazon(query))

    # 2. Flipkart
    if len(results) < 20:
        results.extend(scrape_flipkart(query))

    # 3. Multi-engine search for other big sites
    if len(results) < 20:
        urls = engine_search(query)
        for url in urls:
            results.append(scrape_generic(url))
            if len(results) >= 20:
                break

    return jsonify({
        "product": query,
        "results": results[:20]  # return max 20
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
