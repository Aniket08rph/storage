from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import random
import time

app = Flask(__name__)

# Rotate user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0)",
    "Mozilla/5.0 (Linux; Android 10)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
]

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS)
    }

# Extract price from product page
def extract_price_from_url(url):
    try:
        res = requests.get(url, headers=get_random_headers(), timeout=6)
        soup = BeautifulSoup(res.text, 'html.parser')
        text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', text)
        return prices[0] if prices else "Price not found"
    except Exception:
        return "Error fetching"

@app.route('/')
def home():
    return "✅ CreativeScraper (Brave Default + Rotation) Running!"

# Rotating engines (Brave first)
def get_search_engines(query):
    encoded = query.replace(' ', '+')
    return [
        f"https://search.brave.com/search?q={encoded}",
        f"https://www.startpage.com/do/search?query={encoded}",
        f"https://lite.qwant.com/?q={encoded}",
        f"https://yep.com/search?q={encoded}"
    ]

# Extract links from search results
def extract_links(soup):
    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().strip()

        if "http" in href:
            full_url = unquote(href)
        elif "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
        else:
            continue

        if any(x in text.lower() for x in ['₹', 'price', '$', 'rs']):
            results.append((text, full_url))

    return results

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    final_results = []

    for engine_url in get_search_engines(query):
        try:
            res = requests.get(engine_url, headers=get_random_headers(), timeout=6)
            soup = BeautifulSoup(res.text, "html.parser")
            links = extract_links(soup)

            for text, link in links:
                if len(final_results) >= 10:
                    break

                price = extract_price_from_url(link)
                if price not in ["Price not found", "Error fetching"]:
                    final_results.append({
                        "title": text,
                        "url": link,
                        "price": price
                    })

        except Exception as e:
            continue

        if len(final_results) >= 5:
            break  # Got enough

    if final_results:
        return jsonify({
            "product": query,
            "results": final_results[:10]
        })
    else:
        return jsonify({
            "product": query,
            "results": [],
            "error": "Not enough valid results found. Try more common product keywords."
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
