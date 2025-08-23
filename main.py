from flask import Flask, request, jsonify
import requests, random, re, time
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

# -----------------------------
# Rotating User Agents
# -----------------------------
USER_AGENTS = [
    # Desktop
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/126.0",
    # Mobile
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Samsung Galaxy S22) AppleWebKit/537.36 Chrome/123.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; Redmi Note 9) AppleWebKit/537.36 Chrome/121.0 Mobile Safari/537.36",
    # iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 Version/16.5 Mobile/15E148 Safari/604.1"
]

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

# -----------------------------
# Extract price from product pages
# -----------------------------
def extract_price_from_url(url):
    try:
        res = requests.get(url, headers=get_headers(), timeout=8)
        soup = BeautifulSoup(res.text, 'html.parser')

        price_text = soup.get_text(" ", strip=True)
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        for pattern in patterns:
            prices = re.findall(pattern, price_text)
            if prices:
                return prices[0]

        return "Price not found"
    except Exception:
        return "Error fetching"

# -----------------------------
# Search engines (scraper-friendly)
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "ecosia": "https://www.ecosia.org/search?q={query}",
    "metager": "https://metager.org/meta/meta.ger3?eingabe={query}"
}

# -----------------------------
# Shopping site filter
# -----------------------------
SHOPPING_SITES = [
    "amazon", "flipkart", "snapdeal", "croma", "reliancedigital",
    "tatacliq", "shopclues", "paytmmall", "myntra"
]

# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Multi-Engine + Shopping filter) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query required'}), 400

    search_query = f"{query} Buy in India"

    results = []
    seen_urls = set()
    max_results = 20

    for engine_name, engine_url in SEARCH_ENGINES.items():
        try:
            search_url = engine_url.format(query=search_query.replace(' ', '+'))
            res = requests.get(search_url, headers=get_headers(), timeout=8)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.find_all('a', href=True):
                href = a['href']

                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]
                text = a.get_text().strip()

                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                # ✅ Only allow shopping/product sites
                if not any(site in clean_url.lower() for site in SHOPPING_SITES):
                    continue

                price = extract_price_from_url(clean_url)
                if price not in ["Price not found", "Error fetching"]:
                    results.append({
                        "title": text or engine_name,
                        "url": clean_url,
                        "price": price,
                        "source": engine_name
                    })

                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break

            time.sleep(random.uniform(0.6, 1.5))  # avoid bans

        except Exception:
            continue

    return jsonify({
        "product": search_query,
        "results": results[:max_results]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
