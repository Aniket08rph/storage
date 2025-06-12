from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import requests
from urllib.parse import unquote
import re

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper is Live!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    query = data.get("query")

    if not query:
        return jsonify({"error": "Query is required"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # DuckDuckGo search
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+buy+online"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        if "/l/?" in href and "uddg=" in href:
            clean_url = unquote(href.split("uddg=")[-1].split("&rut=")[0])

            if clean_url not in seen and any(x in text.lower() for x in ["₹", "$", "price", "buy", "offer"]):
                seen.add(clean_url)

                try:
                    prod_page = requests.get(clean_url, headers=headers, timeout=5)
                    prod_soup = BeautifulSoup(prod_page.text, "html.parser")

                    price = extract_price(prod_soup)
                except:
                    price = "Error fetching"

                results.append({
                    "title": text,
                    "url": clean_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]
    })

# 🔍 Basic price extraction logic
def extract_price(soup):
    price_patterns = [
        r'₹\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?',
        r'\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?',
    ]
    for tag in soup.find_all(["span", "div", "p", "h1", "h2", "h3"]):
        text = tag.get_text()
        for pattern in price_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
    return "Price not found"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
