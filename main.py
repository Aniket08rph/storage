from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper is live!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+price"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            real_url = unquote(href.split("uddg=")[-1])
            text = a.get_text().strip()
            if 'price' in text.lower() or '₹' in text:
                results.append({
                    "title": text,
                    "url": real_url
                })

    return jsonify({
        "product": query,
        "results": results[:5]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
