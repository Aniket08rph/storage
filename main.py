from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# Function to extract price from a product page
def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Extract ₹ prices
        price_text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', price_text)
        if prices:
            return prices[0]
        return "Price not found"

    except Exception:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Phase 3 Lite) is running!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    res = requests.get(search_url, headers=headers, timeout=5)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']

        # FIXED ONLY THIS LINE, REST SAME
        if "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]
            text = a.get_text().strip()

            # Basic filter
            if '₹' in text or 'price' in text.lower() or '$' in text or 'rs' in text.lower():
                price = extract_price_from_url(clean_url)

                # 🚫 Skip bad results
                if price not in ["Price not found", "Error fetching"]:
                    results.append({
                        "title": text,
                        "url": clean_url,
                        "price": price
                    })

    return jsonify({
        "product": query,
        "results": results[:5]  # Max 5 clean price results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
