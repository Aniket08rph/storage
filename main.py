from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# Function to extract price from product page HTML
def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Look for ₹ pattern in entire text
        price_text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', price_text)

        if prices:
            return prices[0]  # Return first match
        else:
            return "Price not found"
    except Exception:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Final Version) is Live!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    # DuckDuckGo HTML search
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    res = requests.get(search_url, headers=headers, timeout=5)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []

    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]
            text = a.get_text().strip()

            # Basic filter: only process if text seems price-related
            if '₹' in text or 'price' in text.lower() or '$' in text or 'rs' in text.lower():
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
