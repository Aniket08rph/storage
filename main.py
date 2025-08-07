from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import random
import time

app = Flask(__name__)

# Expanded list with desktop, Android Chrome, iOS Safari, and Firefox Android
USER_AGENTS = [
    # Desktop Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",

    # macOS Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.1 Safari/605.1.15",

    # Android Chrome
    "Mozilla/5.0 (Linux; Android 11; SM-A107F) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36",

    # iPhone Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/14.0 Mobile/15A372 Safari/604.1",

    # ✅ Firefox for Android (realistic)
    "Mozilla/5.0 (Android 11; Mobile; rv:109.0) Gecko/109.0 Firefox/109.0"
]

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://search.brave.com/"
    }

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
    return "✅ CreativeScraper (Improved Rotation + Brave + Fallbacks) Running!"

def get_search_engines(query):
    encoded = query.replace(' ', '+')
    return [
        f"https://www.startpage.com/do/search?query={encoded}",
        f"https://lite.qwant.com/?q={encoded}",
        f"https://yep.com/search?q={encoded}",
        f"https://search.brave.com/search?q={encoded}"
    ]

def extract_links(soup):
    results = []
    seen_urls = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().strip()

        if href.startswith("http") and not any(x in href for x in ["#", "/settings", "/feedback", "/images", "javascript:"]):
            url = href
        elif "uddg=" in href:
            url = unquote(href.split("uddg=")[-1])
        else:
            continue

        if url in seen_urls:
            continue
        seen_urls.add(url)

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
            print(f"🔍 Searching: {engine_url}")
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

                time.sleep(0.3)

        except Exception as e:
            print(f"❌ Error with engine {engine_url}: {e}")
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
