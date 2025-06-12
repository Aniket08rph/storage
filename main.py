# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ✅ Phase 3 - AI-style query cleaner
def clean_query(raw_query):
    if not raw_query:
        return ""

    query = raw_query.lower()

    # 🔥 Remove noise/marketing words
    remove_words = [
        'buy', 'cheap', 'best', 'top', 'latest', 'mobile', 'online',
        '2024', 'price in india', 'under', 'offer', 'deal', 'cost'
    ]
    for word in remove_words:
        query = query.replace(word, '')

    # 🔁 Normalize
    query = query.replace('iphone fifteen', 'iphone 15')
    query = query.replace('fifteen', '15')

    # ❌ Remove junk characters
    query = re.sub(r'[^a-zA-Z0-9\s]', '', query)

    return query.strip() + ' price'

# ✅ Home route
@app.route('/')
def home():
    return "🔥 PriceWise Scraper API is running!"

# ✅ Price scrape endpoint
@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    raw_query = data.get('query')

    if not raw_query:
        return jsonify({'error': 'Missing query'}), 400

    query = clean_query(raw_query)
    logging.info(f"Scraping for: {query}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) Chrome/115.0.0.0 Safari/537.36"
    }

    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    
    try:
        res = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        return jsonify({"error": f"Failed to fetch search results: {str(e)}"}), 500

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0].strip()
            text = a.get_text().strip()

            if any(keyword in text.lower() for keyword in ['price', '₹', '$']):
                results.append({
                    "title": text,
                    "url": clean_url
                })

    return jsonify({
        "product": query,
        "results": results[:5] if results else [{"title": "No price results found", "url": ""}]
    })

# ✅ Run the server
if __name__ == '__main__':
    # For Replit, Render, Railway, etc.
    app.run(host='0.0.0.0', port=8080)
