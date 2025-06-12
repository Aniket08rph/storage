from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper is live with INR price support!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # 🔁 Target only Indian ecommerce platforms
    search_query = f"{query} price site:flipkart.com OR site:amazon.in"
    url = f"https://html.duckduckgo.com/html/?q={search_query.replace(' ', '+')}"

    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            # Decode DuckDuckGo redirect URL
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]  # Remove tracker

            text = a.get_text().strip()
            if '₹' in text:  # Only include INR prices
                results.append({
                    "title": text,
                    "url": clean_url
                })

    return jsonify({
        "product": query,
        "results": results[:5] if results else "No INR prices found"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
