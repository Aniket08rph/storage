from flask import Flask, request, jsonify
import os, requests, re, random, time, asyncio
from bs4 import BeautifulSoup
from urllib.parse import unquote
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
import google.generativeai as genai  # ✅ Gemini

app = Flask(__name__)

# -----------------------------
# Gemini Setup
# -----------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
    gemini_model = None

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
# Playwright Scraper (JS-heavy sites)
# -----------------------------
async def playwright_scrape(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await stealth_async(page)
            await page.goto(url, timeout=20000)
            content = await page.content()
            await browser.close()
            return content
    except Exception:
        return None

# -----------------------------
# Extract price + image (basic)
# -----------------------------
def extract_price_image_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')

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

    return {
        "price": price,
        "image": img_url if img_url else "Image not found"
    }

# -----------------------------
# AI-powered Extraction (Gemini)
# -----------------------------
def ai_extract_price_image(html):
    """ Use Gemini to intelligently extract product details from messy HTML """
    if not gemini_model:
        return None

    prompt = """
    You are an e-commerce parser AI. 
    Extract the main product name, price, and main image URL from the following HTML. 
    Return only valid JSON in this format:
    {"title": "...", "price": "...", "image": "..."}
    """

    try:
        resp = gemini_model.generate_content([prompt, html])
        return resp.text
    except Exception:
        return None

# -----------------------------
async def extract_price_image_from_url(url):
    try:
        res = requests.get(url, headers=get_headers(), timeout=8)
        html = res.text if res.status_code == 200 else None

        if not html or any(x in url for x in ["amazon", "flipkart", "croma"]):
            html = await playwright_scrape(url)

        if not html:
            return {"price": "Error fetching", "image": None}

        # First try regex extraction
        data = extract_price_image_from_html(html)

        # If Gemini is available, refine the result
        ai_data = ai_extract_price_image(html)
        if ai_data:
            return ai_data

        return data
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

# -----------------------------
# Block junk domains
# -----------------------------
BLOCKED_DOMAINS = [
    "wikipedia.org", "quora.com", "youtube.com", "reddit.com",
    "news", "blog", "review", "howto", "tutorial"
]

def is_shopping_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper with Playwright + Gemini AI is running!"

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

    async def run_scraper():
        for engine_name, engine_url in SEARCH_ENGINES.items():
            try:
                search_url = engine_url.format(query=search_query.replace(' ', '+'))
                res = requests.get(search_url, headers=get_headers(), timeout=8)
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
                    text = a.get_text().strip()

                    if clean_url in seen_urls or not is_shopping_url(clean_url):
                        continue
                    seen_urls.add(clean_url)

                    if any(term in text.lower() for term in ['₹', 'price', '$', 'rs', 'buy']):
                        data = await extract_price_image_from_url(clean_url)

                        if isinstance(data, str):  # If Gemini returned raw JSON text
                            try:
                                import json
                                data = json.loads(data)
                            except Exception:
                                data = {"price": "AI parse error", "image": None}

                        if data["price"] not in ["Price not found", "Error fetching"]:
                            results.append({
                                "title": text or data.get("title", "Unknown"),
                                "url": clean_url,
                                "price": data["price"],
                                "image": data["image"]
                            })

                    if len(results) >= 20:
                        break

                if len(results) >= 20:
                    break
                time.sleep(random.uniform(1, 2))

            except Exception:
                continue

        return results[:20]

    final_results = asyncio.run(run_scraper())

    return jsonify({
        "product": search_query,
        "results": final_results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
