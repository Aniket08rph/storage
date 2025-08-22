from flask import Flask, request, jsonify
import requests, random, time, re
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

# -----------------------------
# Rotating User Agents
# -----------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/126.0"
]

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

# -----------------------------
# Extract price from product pages
# -----------------------------
def extract_price_from_url(url):
    try:
        res = requests.get(url, headers=get_headers(), timeout=7)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Look for common price patterns
        text = soup.get_text(" ", strip=True)
        patterns = [r'₹\s?[0-9,]+', r'Rs\.?\s?[0-9,]+', r'\$[0-9,.]+']
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0)

        return None
    except Exception:
        return None

# -----------------------------
# Search Engines (no Google/Yahoo)
# -----------------------------
SEARCH_ENGINES = {
    "brave": "https://search.brave.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "metager": "https://metager.org/meta/meta.ger3?eingabe={query}",
    "ecosia": "https://www.ecosia.org/search?q={query}&simple=1"
}

# -----------------------------
@app.route('/')
def home():
    return "🔥 AI Shopping Scraper (Multi-Engine, Anti-block) is running!"

#✅ Health check endpoint for UptimeRobot

@app.route('/ping')
def ping():
return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    search_query = f"{query} Buy in India".replace(" ", "+")
    results = []
    seen_urls = set()

    for engine, url in SEARCH_ENGINES.items():
        try:
            search_url = url.format(query=search_query)
            res = requests.get(search_url, headers=get_headers(), timeout=7)
            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]

                # Clean redirect links
                if "uddg=" in href:
                    full_url = unquote(href.split("uddg=")[-1])
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                clean_url = full_url.split("&rut=")[0]

                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                text = a.get_text().strip()[:120]
                price = extract_price_from_url(clean_url)

                if price:
                    results.append({
                        "title": text or engine,
                        "url": clean_url,
                        "price": price,
                        "source": engine
                    })

                if len(results) >= 12:  # cap results per engine
                    break

        except Exception:
            continue

        # Random delay between engines (avoid bans)
        time.sleep(random.uniform(0.8, 2.0))

        if len(results) >= 25:  # stop after enough results
            break

    return jsonify({
        "product": query,
        "results": results or [{"error": "No results found"}]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
