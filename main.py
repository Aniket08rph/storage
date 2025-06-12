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

    url = f"https://www.google.com/search?q={query.replace(' ', '+')}+price"
    headers = {"User-Agent": "Mozilla/5.0"}

    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    prices = [span.get_text() for span in soup.find_all("span") if "₹" in span.get_text()][:3]

    return jsonify({"product": query, "prices": prices})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
