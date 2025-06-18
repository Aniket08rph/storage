from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# 🧠 Improved price extraction with custom rules
def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=7)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_text = soup.get_text()

        # Flipkart logic
        if "flipkart.com" in url:
            flip_price = soup.select_one("._30jeq3")  # Flipkart's price class
            if flip_price:
                return flip_price.text.strip()

        # Amazon logic
        if "amazon.in" in url or "amazon.com" in url:
            amz_price = soup.select_one("#priceblock_ourprice, #priceblock_dealprice, .a-price-whole")
            if amz_price:
                return amz_price.text.strip()

        # Generic price ₹ pattern
        prices = re.findall(r'₹\s?[0-9,]+', price_text)
        if prices:
            return prices[0]

        return "Price not found"

    except Exception as e:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Phase 3 Enhanced) is live!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    # DuckDuckGo search
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    res = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]
            text = a.get_text().strip()

            if '₹' in text or 'price' in text.lower() or 'Buy' in text or 'Amazon' in text or 'Flipkart' in clean_url:
                price = extract_price_from_url(clean_url)
                results.append({
                    "title": text,
                    "url": clean_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
