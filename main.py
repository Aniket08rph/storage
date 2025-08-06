from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import random

app = Flask(__name__)

# Function to extract price from a product page
def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        price_text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', price_text)
        if prices:
            return prices[0]
        return "Price not found"

    except Exception:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Phase 3 Rotating) is running!"

# === Utility: Search Engines ===
def get_search_engines(query):
    return [
        f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}",
        f"https://www.startpage.com/do/search?query={query.replace(' ', '+')}",
        f"https://lite.qwant.com/?q={query.replace(' ', '+')}",
        f"https://yep.com/search?q={query.replace(' ', '+')}",
    ]

# === Utility: Clean URL extraction ===
def extract_links(soup):
    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().strip()

        # Try to extract direct URL
        if "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        if '₹' in text or 'price' in text.lower() or '$' in text or 'rs' in text.lower():
            results.append((text, full_url))
    return results

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    # Rotate search engines
    for url in get_search_engines(query):
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            raw_links = extract_links(soup)

            final_results = []
            for text, clean_url in raw_links:
                price = extract_price_from_url(clean_url)

                if price not in ["Price not found", "Error fetching"]:
                    final_results.append({
                        "title": text,
                        "url": clean_url,
                        "price": price
                    })
                if len(final_results) >= 5:
                    break

            if final_results:
                return jsonify({
                    "product": query,
                    "results": final_results
                })

        except Exception:
            continue  # Try next search engine

    return jsonify({
        "error": "All sources failed. Try again later."
    }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
