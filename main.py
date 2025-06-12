from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper Phase 2 is Live!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # DuckDuckGo search
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+buy+online+price"
    res = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            real_url = unquote(href.split("uddg=")[-1])
            clean_url = real_url.split("&rut=")[0]
            title = a.get_text().strip()

            if '₹' in title or 'price' in title.lower() or '$' in title or 'buy' in title.lower():
                price = extract_price_from_url(clean_url)
                results.append({
                    "title": title if title else clean_url,
                    "url": clean_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]  # Limit to 5 results
    })


def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        page = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(page.text, "html.parser")

        text = soup.get_text()

        # Look for ₹ price
        if "₹" in text:
            import re
            matches = re.findall(r"₹\s?[\d,]+", text)
            if matches:
                return matches[0]

        # Look for $ price (for amazon.com fallback)
        if "$" in text:
            matches = re.findall(r"\$\s?[\d,]+", text)
            if matches:
                return matches[0]

        return "Price not found"
    except Exception as e:
        return "Error fetching"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
