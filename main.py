from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup

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

    links = []
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        if '₹' in text or 'price' in text:
            links.append(a['href'])

    return jsonify({
        "product": query,
        "results": links[:5]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
