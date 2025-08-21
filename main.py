from flask import Flask, request, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, quote_plus
import re, time, random, concurrent.futures

app = Flask(__name__)

# -----------------------------
# Robust session with retries/backoff
# -----------------------------
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

SESSION = make_session()

# -----------------------------
# UAs and headers (stealthier)
# -----------------------------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
]

def default_headers():
    return {
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Connection": "keep-alive",
    }

# -----------------------------
# Price extraction (selectors + regex fallback)
# -----------------------------
CURRENCY_PATTERNS = [
    r'₹\s?[\d,]+(?:\.\d+)?',
    r'Rs\.?\s?[\d,]+(?:\.\d+)?',
    r'\$\s?[\d,]+(?:\.\d+)?'
]

SITE_SELECTORS = {
    "amazon.in": [".a-price .a-offscreen", "#corePriceDisplay_desktop_feature_div .a-offscreen"],
    "flipkart.com": ["._30jeq3", "._1vC4OE"],
    "croma.com": [".pdp-price .amount"],
    "reliancedigital.in": [".pdp__finalPrice", ".price"],
    "tatacliq.com": [".price__value"]
}

def _first_currency(text):
    if not text: return None
    for p in CURRENCY_PATTERNS:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None

def extract_price_from_html(url, html):
    domain = urlparse(url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")

    # 1. site-specific selectors
    for host, selectors in SITE_SELECTORS.items():
        if host in domain:
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    cur = _first_currency(el.get_text(" ", strip=True))
                    if cur: return cur

    # 2. meta tags
    for m in soup.find_all("meta"):
        if m.get("property", "").lower().endswith("price:amount") or m.get("itemprop") == "price":
            val = m.get("content") or m.get("value") or ""
            cur = _first_currency(val)
            if cur: return cur

    # 3. whole-page scan
    return _first_currency(soup.get_text(" ", strip=True))

def extract_price_from_url(url, timeout=8):
    try:
        r = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code != 200:
            return None
        if "text/html" not in r.headers.get("Content-Type", ""):
            return None
        return extract_price_from_html(url, r.text)
    except Exception:
        return None

# -----------------------------
# Direct shopping search URLs
# -----------------------------
SHOPPING_SITES = {
    "amazon": "https://www.amazon.in/s?k={query}",
    "flipkart": "https://www.flipkart.com/search?q={query}",
    "croma": "https://www.croma.com/search/?text={query}",
    "reliance": "https://www.reliancedigital.in/search?q={query}:relevance",
    "tatacliq": "https://www.tatacliq.com/search/?searchCategory=all&text={query}"
}

SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}"
}

# -----------------------------
# Helpers
# -----------------------------
BLOCKED_DOMAINS = ["wikipedia", "youtube", "facebook", "twitter", "instagram", "reddit", "medium"]
PATH_HINTS = ["product", "p/", "shop", "store", "buy", "product-category"]

def clean_outgoing_url(href):
    if not href: return None
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("&rut=")[0]
    if "uddg=" in href:
        try: return unquote(href.split("uddg=")[-1].split("&")[0])
        except: return None
    if href.startswith("/"):
        if "q=" in href:
            q = href.split("q=")[-1].split("&")[0]
            if q.startswith("http"):
                return unquote(q)
    return None

def is_valid_shopping_url(url):
    try:
        if not url.startswith("http"): return False
        host = urlparse(url).netloc.lower()
        if any(b in host for b in BLOCKED_DOMAINS): return False
        if any(s in host for s in SITE_SELECTORS.keys()): return True
        path_q = (urlparse(url).path + "?" + (urlparse(url).query or "")).lower()
        return any(hint in path_q for hint in PATH_HINTS)
    except Exception:
        return False

def extract_links_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        url = clean_outgoing_url(a["href"])
        if not url: continue
        title = a.get_text(" ", strip=True)[:200]
        out.append((url, title))
    return out

def fetch_html(url, timeout=8):
    try:
        r = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code != 200: return None
        if "text/html" not in r.headers.get("Content-Type", ""): return None
        return r.text
    except: return None

# -----------------------------
# Endpoints
# -----------------------------
@app.route("/")
def home():
    return "🔥 CreativeScraper (Pro version) is running!"

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max_results", 10))
    if not query:
        return jsonify({"error": "Query required"}), 400

    search_query = f"{query} buy in India"
    encoded = quote_plus(search_query)

    candidates = []
    seen = set()

    # 1. Direct shopping sites first
    for site, tmpl in SHOPPING_SITES.items():
        url = tmpl.format(query=encoded)
        html = fetch_html(url)
        if not html: continue
        links = extract_links_from_html(html)
        for href, title in links:
            if not is_valid_shopping_url(href): continue
            if href in seen: continue
            seen.add(href)
            candidates.append({"title": title, "url": href, "source": site})

    # 2. Fallback to search engines
    for engine, tmpl in SEARCH_ENGINES.items():
        url = tmpl.format(query=encoded)
        html = fetch_html(url)
        if not html: continue
        links = extract_links_from_html(html)
        for href, title in links:
            if not is_valid_shopping_url(href): continue
            if href in seen: continue
            seen.add(href)
            candidates.append({"title": title, "url": href, "source": engine})

    # 3. Fetch prices concurrently
    top = candidates[:30]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(extract_price_from_url, c["url"]): i for i, c in enumerate(top)}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            try:
                price = fut.result()
            except:
                price = None
            if price:
                top[i]["price"] = price

    # 4. Rank (price + domain priority)
    def rank_key(it):
        host = urlparse(it["url"]).netloc.lower()
        score = 0
        if it.get("price"): score += 100
        if "amazon.in" in host: score += 50
        if "flipkart.com" in host: score += 45
        if any(x in host for x in ["croma.com", "reliancedigital.in", "tatacliq.com"]): score += 30
        return -score

    top.sort(key=rank_key)
    final = top[:max_results]

    return jsonify({"product": search_query, "results": final or [{"error": "No shopping results"}]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
