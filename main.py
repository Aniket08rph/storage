from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# ✅ List of trusted ecommerce domains
trusted_domains = [
    "flipkart.com",
    "amazon.",
    "croma.com",
    "reliancedigital.in"
]

# 🔍 Extract price from valid product URL
def extract_price_from_url(url):
    if not any(domain in url for domain in trusted_domains):
        return "Unsupported site"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Scan visible text for ₹ price pattern
        price_text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', price_text)

        if prices:
            return prices[0]
        else:
            return "Price not found"

    except Exception as e:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Phase 3 Final) is live and filtered!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    # DuckDuckGo Search
    ddg_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    res = requests.get(ddg_url, headers=headers, timeout=5)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []

    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]
            text = a.get_text().strip()

            # ✅ Filter by supported domain
            if any(domain in clean_url for domain in trusted_domains):
                price = extract_price_from_url(clean_url)
                results.append({
                    "title": text,
                    "url": clean_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]  # Limit to top 5
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
