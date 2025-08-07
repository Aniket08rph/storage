from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import random
import time

app = Flask(__name__)

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

def get_search_engines(query):
    encoded = query.replace(' ', '+')
    return [
        f"https://search.brave.com/search?q={encoded}",
        f"https://www.startpage.com/do/search?query={encoded}",
        f"https://lite.qwant.com/?q={encoded}",
        f"https://yep.com/search?q={encoded}"
    ]

# Improved link extraction
def extract_links(soup):
    results = []
    seen_urls = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().strip()

        # Clean URL
        if "uddg=" in href:
            url = unquote(href.split("uddg=")[-1])
        elif href.startswith("http") and not any(x in href for x in ["#","/settings", "/feedback", "/images"]):
            url = href
        else:
            continue

        # Filter duplicate and junk URLs
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Only accept links with price-related keywords
        if any(word in text.lower() for word in ['₹', 'price', '$', 'rs']):
            results.append((text, url))

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

                time.sleep(0.3)  # optional delay to avoid fast requests

        except Exception:
            continue

        if len(final_results) >= 5:
            break

    if final_results:
        return jsonify({
            "product": query,
            "results": final_results[:10]
        })
    else:
        return jsonify({
            "product": query,
            "results": [],
            "error": "Not enough valid results found. Try a more specific product name."
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
