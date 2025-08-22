from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote, quote_plus
import re, random, time

app = Flask(__name__)

# -----------------------------
# User Agents pool (rotate each request to reduce blocking)
# -----------------------------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/126.0"
]

def headers():
    return {"User-Agent": random.choice(UAS)}

# -----------------------------
# Function to extract price from product pages
# -----------------------------
def extract_price_from_url(url):
    try:
        res = requests.get(url, headers=headers(), timeout=7)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Site-specific selectors first
        if "amazon." in url:
            el = soup.select_one(".a-price .a-offscreen")
            if el: return el.text.strip()
        if "flipkart.com" in url:
            el = soup.select_one("._30jeq3")
            if el: return el.text.strip()
        if "croma.com" in url:
            el = soup.select_one(".pdp-price .amount")
            if el: return el.text.strip()
        if "reliancedigital.in" in url:
            el = soup.select_one(".pdp__finalPrice")
            if el: return el.text.strip()
        if "tatacliq.com" in url:
            el = soup.select_one(".price__value")
            if el: return el.text.strip()

        # Fallback regex scan for any ₹, Rs, or $
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
# Search engines + direct shopping sites
# -----------------------------
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "googlelite": "https://www.google.com/search?q={query}&hl=en&gl=IN&gbv=1",
    "yahoo": "https://search.yahoo.com/search?p={query}"
}

SHOPPING_SITES = {
    "amazon": "https://www.amazon.in/s?k={query}",
    "flipkart": "https://www.flipkart.com/search?q={query}",
    "croma": "https://www.croma.com/search/?text={query}",
    "reliance": "https://www.reliancedigital.in/search?q={query}:relevance",
    "tatacliq": "https://www.tatacliq.com/search/?searchCategory=all&text={query}"
}

# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Multi-Engine + Direct Sites) is running!"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query required"}), 400

    search_query = f"{query} Buy in India"
    encoded = quote_plus(search_query)

    results = []
    seen_urls = set()

    # -----------------------------
    # Search Engines First
    # -----------------------------
    for engine, url in SEARCH_ENGINES.items():
        try:
            res = requests.get(url.format(query=encoded), headers=headers(), timeout=7)
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

                text = a.get_text().strip()[:150]
                price = extract_price_from_url(clean_url)

                if price:
                    results.append({
                        "title": text or engine,
                        "url": clean_url,
                        "price": price,
                        "source": engine
                    })

                if len(results) >= 15:
                    break
            if len(results) >= 15:
                break
        except Exception:
            continue
        time.sleep(0.5)

    # -----------------------------
    # Direct Shopping Sites
    # -----------------------------
    for site, url in SHOPPING_SITES.items():
        try:
            res = requests.get(url.format(query=encoded), headers=headers(), timeout=7)
            soup = BeautifulSoup(res.text, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/"):
                    base = url.split("/")[0] + "//" + url.split("/")[2]
                    full_url = base + href
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                text = a.get_text().strip()[:150]
                price = extract_price_from_url(full_url)

                if price:
                    results.append({
                        "title": text or site,
                        "url": full_url,
                        "price": price,
                        "source": site
                    })

                if len(results) >= 25:
                    break
        except Exception:
            continue
        time.sleep(0.8)

    return jsonify({
        "product": search_query,
        "results": results[:25] or [{"error": "No results found"}]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
