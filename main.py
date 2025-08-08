from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re
import random
import logging

app = Flask(__name__)

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -----------------------------
# User agents pool for rotation
# -----------------------------
USER_AGENTS = [
    # Desktop Chrome
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

    # Firefox for Android
    "Mozilla/5.0 (Android 11; Mobile; rv:109.0) Gecko/109.0 Firefox/109.0"
]

# -----------------------------
# Helper functions
# -----------------------------
def get_random_headers():
    """Return headers with a random realistic User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://search.brave.com/"
    }

def normalize_query(query: str) -> str:
    """Clean extra spaces, trim, and make safe for URLs."""
    return "+".join(query.strip().split())

def extract_price_from_text(text: str):
    """Find the first price-like pattern in raw text."""
    patterns = [
        r'₹\s?[0-9,]+',   # Indian Rupee
        r'Rs\.?\s?[0-9,]+',
        r'INR\s?[0-9,]+',
        r'\$[0-9,.]+'     # Dollar fallback
    ]
    for pattern in patterns:
        prices = re.findall(pattern, text)
        if prices:
            return prices[0]
    return None

def extract_price_from_url(url: str) -> str:
    """Fetch page and try to extract price."""
    try:
        res = requests.get(url, headers=get_random_headers(), timeout=8)
        if res.status_code != 200:
            return None
        soup = BeautifulSoup(res.text, 'html.parser')
        text = soup.get_text(separator=" ", strip=True)
        return extract_price_from_text(text)
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return None

def get_search_engines(query: str):
    """Return a list of search engine URLs for the query."""
    return [
        f"https://www.startpage.com/do/search?query={query}",
        f"https://lite.qwant.com/?q={query}",
        f"https://yep.com/search?q={query}",
        f"https://search.brave.com/search?q={query}"
    ]

def extract_links(soup: BeautifulSoup):
    """Extract product-related links from search engine HTML."""
    results = []
    seen_urls = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().strip()

        # Normalize href
        if href.startswith("http"):
            url = href
        elif "uddg=" in href:
            url = unquote(href.split("uddg=")[-1])
        else:
            continue

        # Avoid duplicates and irrelevant links
        if url in seen_urls or any(x in href for x in ["#", "/settings", "/feedback", "/images", "javascript:"]):
            continue

        seen_urls.add(url)

        # Keep if price-related terms or numeric patterns exist
        if any(term in text.lower() for term in ['₹', 'price', 'rs', '$', 'buy']) or extract_price_from_text(text):
            results.append((text, url))

    return results

# -----------------------------
# Flask Routes
# -----------------------------
@app.route('/')
def home():
    return jsonify({"status": "ok", "message": "Price scraper is running"})

@app.route('/scrape', methods=['POST'])
def scrape():
    """Main scraping endpoint."""
    try:
        data = request.get_json(force=True)
        query_raw = data.get('query', '')

        if not query_raw.strip():
            return jsonify({'error': 'Query is required'}), 400

        query = normalize_query(query_raw)
        final_results = []

        for engine_url in get_search_engines(query):
            logging.info(f"Searching: {engine_url}")
            try:
                res = requests.get(engine_url, headers=get_random_headers(), timeout=8)
                soup = BeautifulSoup(res.text, "html.parser")
                links = extract_links(soup)

                for text, link in links:
                    if len(final_results) >= 10:
                        break

                    price = extract_price_from_url(link)
                    if not price:
                        # Try also extracting from the search result snippet itself
                        price = extract_price_from_text(text)

                    if price:
                        final_results.append({
                            "title": text,
                            "url": link,
                            "price": price
                        })

            except Exception as e:
                logging.error(f"Error with engine {engine_url}: {e}")
                continue

            if len(final_results) >= 5:
                break

        if final_results:
            return jsonify({
                "product": query_raw.strip(),
                "results": final_results[:10]
            })
        else:
            return jsonify({
                "product": query_raw.strip(),
                "results": [],
                "error": "Could not find valid prices. Try refining your query."
            }), 404

    except Exception as e:
        logging.exception("Unhandled error during scrape")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# -----------------------------
# Main
# -----------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
