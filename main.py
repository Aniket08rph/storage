from flask import Flask, request, jsonify
import requests, os, re, random, time, json
from bs4 import BeautifulSoup
from urllib.parse import unquote
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
# Shopping & AI enrichment domains
# -----------------------------
SHOPPING_DOMAINS = ["flipkart.com", "amazon.in", "nykaa.com", "myntra.com", "tatacliq.com"]
BLOCKED_DOMAINS = ["wikipedia.org", "quora.com", "youtube.com", "reddit.com", "news", "blog", "howto", "tutorial"]

def is_shopping_site(url):
    return any(domain in url.lower() for domain in SHOPPING_DOMAINS)

def is_allowed_url(url):
    return not any(block in url.lower() for block in BLOCKED_DOMAINS)

# -----------------------------
# Extract full product data (price, image, rating, reviews, brand, discount)
# -----------------------------
def extract_product_data(url):
    try:
        res = requests.get(url, headers=get_headers(), timeout=8)
        soup = BeautifulSoup(res.text, 'html.parser')
        html = res.text

        # --- Price ---
        price = "Price not found"
        price_patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        for pattern in price_patterns:
            match = re.findall(pattern, soup.get_text())
            if match:
                price = match[0]
                break

        # --- Image ---
        img_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]
        else:
            img = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"class": re.compile(r'(product|main).*image', re.I)})
            img_url = img["src"] if img and img.get("src") else None

        # --- Rating ---
        rating = None
        rating_tag = soup.find(attrs={"class": re.compile(r'rating|stars', re.I)})
        if rating_tag:
            rating_match = re.search(r'\d+(\.\d+)?', rating_tag.get_text())
            rating = rating_match.group() if rating_match else None

        # --- Reviews count ---
        reviews_count = None
        rev_tag = soup.find(attrs={"class": re.compile(r'review-count|reviews', re.I)})
        if rev_tag:
            count_match = re.search(r'\d+', rev_tag.get_text().replace(',', ''))
            reviews_count = int(count_match.group()) if count_match else None

        # --- Brand / Seller ---
        brand = None
        brand_tag = soup.find(attrs={"class": re.compile(r'brand|seller', re.I)})
        if brand_tag:
            brand = brand_tag.get_text().strip()

        # --- Discount / Offer ---
        discount = None
        disc_tag = soup.find(attrs={"class": re.compile(r'discount|offer|sale', re.I)})
        if disc_tag:
            discount = disc_tag.get_text().strip()

        data = {
            "title": soup.title.string if soup.title else "Unknown",
            "price": price,
            "image": img_url or "Image not found",
            "rating": rating,
            "reviews_count": reviews_count,
            "brand": brand,
            "discount": discount,
            "url": url
        }

        # --- Gemini AI fallback ---
        if gemini_model:
            try:
                prompt = f"""
                You are an AI e-commerce parser. Extract product info from the HTML.
                Return JSON only with keys: title, price, image, rating, reviews_count, brand, discount
                HTML: {html}
                """
                resp = gemini_model.generate_content([prompt])
                ai_data = resp.text.strip()
                parsed = json.loads(ai_data)
                for k in data.keys():
                    if k in parsed and parsed[k]:
                        data[k] = parsed[k]
            except Exception:
                pass

        return data

    except Exception:
        return {"title": "Error", "price": "Error", "image": None, "rating": None, "reviews_count": None, "brand": None, "discount": None, "url": url}

# -----------------------------
# Search engines
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
@app.route('/')
def home():
    return "🔥 CreativeScraper (Multi-Engine + Gemini AI) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

# -----------------------------
# Scrape endpoint
# -----------------------------
@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query required'}), 400

    search_query = f"{query} Buy Online in India"
    results, seen_urls, ai_sources = [], set(), []

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
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                # Collect all allowed URLs for AI analysis
                if is_allowed_url(clean_url):
                    ai_sources.append(clean_url)

                # Only add shopping sites to results
                if is_shopping_site(clean_url):
                    product_data = extract_product_data(clean_url)
                    results.append(product_data)

            time.sleep(random.uniform(1, 2))
        except Exception:
            continue

    # -----------------------------
    # Final Gemini AI analysis for all results
    # -----------------------------
    ai_analysis = {}
    if gemini_model and results:
        try:
            prompt = f"""
            You are an expert AI shopping assistant. Analyze the following product list and provide:
            - Best options per category
            - Recommendations based on price, rating, reviews
            - Pros/cons summary
            Return as JSON with keys: best_options, recommendations, summary
            Product List: {json.dumps(results)}
            """
            resp = gemini_model.generate_content([prompt])
            ai_analysis = json.loads(resp.text.strip())
        except Exception:
            ai_analysis = {"error": "Gemini analysis failed"}

    return jsonify({
        "product": search_query,
        "shopping_results": results,
        "ai_analysis": ai_analysis,
        "ai_sources_count": len(ai_sources)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
