from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# -----------------------------
# Function to extract price from a product page
# -----------------------------
def extract_price_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10)"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Extract ₹, Rs, or $ prices
        price_text = soup.get_text()
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        for pattern in patterns:
            prices = re.findall(pattern, price_text)
            if prices:
                return prices[0]

        return "Price not found"

    except Exception:
        return "Error fetching"

# -----------------------------
# Search engine URLs
# -----------------------------
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
}

# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Multi-Engine - Bing primary) is running!"

# ✅ Health check
@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200


@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    # Automatically India-focused
    search_query = f"{query} Buy in India"
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10)"}

    results = []
    seen_urls = set()

    for engine_name, engine_url in SEARCH_ENGINES.items():
        try:
            search_url = engine_url.format(query=search_query.replace(' ', '+'))
            res = requests.get(search_url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")

            # -------------------------
            # Engine-specific selectors
            # -------------------------
            if engine_name == "bing":
                anchors = soup.select("li.b_algo h2 a")   # ✅ Bing
            elif engine_name == "brave":
                anchors = soup.select("a.result-title")   # ✅ Brave
            elif engine_name == "qwant":
                anchors = soup.select("a[href]")          # Qwant fallback
            else:
                anchors = soup.find_all("a", href=True)

            for a in anchors:
                href = a.get("href")
                if not href:
                    continue

                # Extract real URLs
                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                text = a.get_text().strip()

                # Filter: must look like a product or have price/currency/domain
                if any(term in text.lower() for term in ['₹', 'price', '$', 'rs']) or any(
                    d in clean_url for d in ["amazon", "flipkart", "croma"]
                ):
                    price = extract_price_from_url(clean_url)
                    if price not in ["Price not found", "Error fetching"]:
                        results.append({
                            "title": text or clean_url,
                            "url": clean_url,
                            "price": price
                        })

                if len(results) >= 10:
                    break

            if len(results) >= 10:
                break

        except Exception as e:
            print(f"[ERROR] {engine_name}: {e}")
            continue

    return jsonify({
        "product": search_query,
        "results": results[:10]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
