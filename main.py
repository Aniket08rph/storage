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
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=6)
        soup = BeautifulSoup(res.text, 'html.parser')

        price_text = soup.get_text()
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        for pattern in patterns:
            prices = re.findall(pattern, price_text)
            if prices:
                return prices[0]

        return None  # no price found
    except Exception:
        return None

# -----------------------------
# Search engine URLs (with fallback order)
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "yahoo": "https://search.yahoo.com/search?p={query}"
}

# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Multi-Engine Fallback) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    # Prevent duplicate "Buy in India"
    if "buy in india" not in query.lower():
        search_query = f"{query} Buy in India"
    else:
        search_query = query

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    results = []
    seen_urls = set()

    # Loop through engines until enough results
    for engine_name, engine_url in SEARCH_ENGINES.items():
        try:
            search_url = engine_url.format(query=search_query.replace(' ', '+'))
            res = requests.get(search_url, headers=headers, timeout=8)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.find_all('a', href=True):
                href = a['href']

                # Extract clean URL
                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]
                text = a.get_text().strip()

                # Skip duplicates
                if clean_url in seen_urls or not text:
                    continue
                seen_urls.add(clean_url)

                # Add to results first (without waiting for price fetch)
                result_item = {"title": text, "url": clean_url}
                price = extract_price_from_url(clean_url)
                if price:
                    result_item["price"] = price
                results.append(result_item)

                if len(results) >= 10:
                    break

            if len(results) >= 10:
                break

        except Exception:
            continue

    return jsonify({
        "product": search_query,
        "results": results[:10]  # Max 10 results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
