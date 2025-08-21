from flask import Flask, request, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, quote_plus
import re, time, random, concurrent.futures

app = Flask(__name__)

# -----------------------------
# Session with retries/backoff
# -----------------------------
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

SESSION = make_session()

# -----------------------------
# User agents & default headers
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
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "close",
    }

# -----------------------------
# Price extraction
# -----------------------------
CURRENCY_PATTERNS = [
    r'₹\s?[\d,]+(?:\.\d+)?',      # INR
    r'Rs\.?\s?[\d,]+',            # Rs
    r'\$\s?[\d,]+(?:\.\d+)?',     # USD
]

SITE_PRICE_SELECTORS = {
    # India-first sites
    "amazon.in": ["#corePriceDisplay_desktop_feature_div .a-offscreen", ".a-price-whole", ".a-price .a-offscreen"],
    "flipkart.com": ["._30jeq3", "._16Jk6d"],
    "croma.com": [".pdp-price .amount", ".new-price .amount", ".pdpPrice"],
    "reliancedigital.in": [".pdp__priceSection .pdp__offerPrice", ".pdp__finalPrice"],
    "tatacliq.com": [".ProductDescription__price", ".ProductDetails__price", ".price__value"],
    "vijaysales.com": [".our_price", ".offerPrice", ".product-price"],
    "snapdeal.com": [".payBlkBig", "#selling-price-id", ".final-price"],
    "moglix.com": [".prod-price", ".price span", ".amount"],
    # Global fallback examples
    "ebay.in": ["#prcIsum", "#mm-saleDscPrc", ".notranslate"],
    "ebay.com": ["#prcIsum", "#mm-saleDscPrc", ".x-price-primary"],
    "aliexpress.com": [".product-price-value", ".product-price-current"],
}

def extract_price_from_html(url, html):
    # Site-specific first
    domain = urlparse(url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")
    for host, selectors in SITE_PRICE_SELECTORS.items():
        if host in domain:
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(" ", strip=True)
                    m = _first_currency(text)
                    if m:
                        return m
    # Generic text scan
    text = soup.get_text(" ", strip=True)
    return _first_currency(text)

def _first_currency(text):
    for pat in CURRENCY_PATTERNS:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None

def fetch_price(url, timeout=8):
    try:
        res = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if res.status_code != 200 or "text/html" not in res.headers.get("Content-Type",""):
            return None
        return extract_price_from_html(url, res.text)
    except Exception:
        return None

# -----------------------------
# Search engines (no Yahoo)
# -----------------------------
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "ecosia": "https://www.ecosia.org/search?q={query}",
    "startpage": "https://www.startpage.com/do/dsearch?query={query}",
    "swisscows": "https://swisscows.com/web?query={query}",
    "metager": "https://metager.org/meta/meta.ger3?eingabe={query}",
    "yep": "https://yep.com/web?q={query}"
}

# -----------------------------
# Direct shopping site searches
# (these often beat general search engines)
# -----------------------------
SHOP_SEARCH_URLS = {
    "amazon.in": "https://www.amazon.in/s?k={query}",
    "flipkart.com": "https://www.flipkart.com/search?q={query}",
    "croma.com": "https://www.croma.com/search/?text={query}",
    "reliancedigital.in": "https://www.reliancedigital.in/search?q={query}",
    "tatacliq.com": "https://www.tatacliq.com/search/?searchCategory=all&text={query}",
    "vijaysales.com": "https://www.vijaysales.com/search/{query}",
    "snapdeal.com": "https://www.snapdeal.com/search?keyword={query}",
    "moglix.com": "https://www.moglix.com/search?query={query}",
}

# -----------------------------
# Allow/Block rules
# -----------------------------
ALLOW_DOMAINS = set(SHOP_SEARCH_URLS.keys()) | {
    "ebay.in", "ebay.com", "aliexpress.com", "shopclues.com", "paytmmall.com"
}
BLOCKED_DOMAINS = {
    "news", "blog", "wikipedia", "youtube", "reddit", "facebook", "twitter",
    "instagram", "quora", "medium", "x.com"
}
ALLOW_PATH_HINTS = {"shop", "store", "buy", "product", "products", "cart", "checkout", "deal"}

def is_shopping_url(url):
    netloc = urlparse(url).netloc.lower()
    host = netloc.split(":")[0]
    # allow if domain is in whitelist
    if any(h in host for h in ALLOW_DOMAINS):
        return True
    # reject if obviously non-shopping
    if any(bad in host for bad in BLOCKED_DOMAINS):
        return False
    # path hints
    path = urlparse(url).path.lower()
    if any(hint in path for hint in ALLOW_PATH_HINTS):
        return True
    # query hints
    qs = urlparse(url).query.lower()
    if any(hint in qs for hint in ALLOW_PATH_HINTS):
        return True
    return False

def clean_outgoing_url(href):
    if not href:
        return None
    if "uddg=" in href:
        try:
            return unquote(href.split("uddg=")[-1].split("&")[0])
        except Exception:
            pass
    if href.startswith("/url?") and "q=" in href:
        # some engines wrap google-style
        try:
            return unquote(href.split("q=")[1].split("&")[0])
        except Exception:
            pass
    if href.startswith("http"):
        return href.split("&rut=")[0]
    return None

# -----------------------------
# HTML listing parsing (very generic)
# -----------------------------
def extract_links(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = clean_outgoing_url(a["href"])
        if not href:
            continue
        title = a.get_text(" ", strip=True)[:200]
        out.append((href, title))
    return out

def fetch_url(url, timeout=10):
    try:
        r = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code != 200:
            return None
        return r.text
    except Exception:
        return None

# -----------------------------
# API routes
# -----------------------------
@app.route("/")
def home():
    return "🔥 Savzaar CreativeScraper — Shopping-First Multi-Source is running!"

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"}), 200

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400

    # India-centric wording kept
    if "buy in india" not in query.lower():
        search_query = f"{query} Buy in India"
    else:
        search_query = query

    encoded = quote_plus(search_query)

    results = []
    seen = set()  # dedupe by normalized URL

    # 1) Direct shopping sites first (higher precision)
    for host, tmpl in SHOP_SEARCH_URLS.items():
        url = tmpl.format(query=encoded)
        html = fetch_url(url)
        if not html:
            continue
        for href, title in extract_links(html):
            if not is_shopping_url(href):
                continue
            key = normalize_key(href)
            if key in seen:
                continue
            seen.add(key)
            results.append({"title": title or host, "url": href})

    # 2) General search engines (recall + diversity)
    for name, tmpl in SEARCH_ENGINES.items():
        url = tmpl.format(query=encoded)
        html = fetch_url(url)
        if not html:
            continue
        for href, title in extract_links(html):
            if not is_shopping_url(href):
                continue
            key = normalize_key(href)
            if key in seen:
                continue
            seen.add(key)
            results.append({"title": title or name, "url": href})

    # 3) Fetch prices concurrently for top 25 collected
    top = results[:25]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_price, item["url"]): i for i, item in enumerate(top)}
        for fut in concurrent.futures.as_completed(futs):
            idx = futs[fut]
            price = None
            try:
                price = fut.result()
            except Exception:
                price = None
            if price:
                top[idx]["price"] = price

    # 4) Basic ranking: sites in allowlist first, then others
    def score(item):
        host = urlparse(item["url"]).netloc.lower()
        base = 0
        if any(h in host for h in ALLOW_DOMAINS):
            base += 5
        if "price" in item.get("title","").lower():
            base += 1
        if "₹" in item.get("title",""):
            base += 2
        if item.get("price"):
            base += 3
        return -base  # sort asc -> highest score first

    top.sort(key=score)

    final = top[:20] if top else [{"error": "No shopping results found"}]
    return jsonify({"product": search_query, "results": final})

# -----------------------------
# Utils
# -----------------------------
def normalize_key(url):
    try:
        u = urlparse(url)
        # strip tracking params
        base = f"{u.scheme}://{u.netloc}{u.path}"
        return base.rstrip("/")
    except Exception:
        return url

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
