from flask import Flask, request, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, parse_qs, quote_plus
import re, time, random, concurrent.futures

app = Flask(__name__)

# -----------------------------
# Robust session (retries/backoff)
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
# Price extraction (selectors + regex)
# -----------------------------
CURRENCY_PATTERNS = [
    r'₹\s?[\d,]+(?:\.\d+)?',
    r'Rs\.?\s?[\d,]+(?:\.\d+)?',
    r'\$\s?[\d,]+(?:\.\d+)?',
]

SITE_PRICE_SELECTORS = {
    "amazon.in": [
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        ".a-price .a-offscreen",
        ".a-price-whole"
    ],
    "flipkart.com": ["._30jeq3", "._16Jk6d"],
    "croma.com": [".pdp-price .amount", ".new-price .amount", ".pdpPrice"],
    "reliancedigital.in": [".pdp__offerPrice", ".pdp__finalPrice"],
    "tatacliq.com": [".ProductDescription__price", ".ProductDetails__price", ".price__value"],
    "vijaysales.com": [".our_price", ".offerPrice", ".product-price"],
    "snapdeal.com": [".payBlkBig", "#selling-price-id", ".final-price"],
    "moglix.com": [".prod-price", ".price span", ".amount"],
    "ebay.in": ["#prcIsum", "#mm-saleDscPrc", ".notranslate"],
    "ebay.com": ["#prcIsum", "#mm-saleDscPrc", ".x-price-primary"],
    "aliexpress.com": [".product-price-value", ".product-price-current"],
}

META_PRICE_HINTS = [
    ('meta', {'property': 'product:price:amount'}),
    ('meta', {'property': 'og:price:amount'}),
    ('meta', {'itemprop': 'price'}),
    ('span', {'itemprop': 'price'}),
]

def _first_currency(text):
    if not text:
        return None
    for pat in CURRENCY_PATTERNS:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None

def extract_price_from_html(url, html):
    domain = urlparse(url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")

    # meta hints
    for tag, attrs in META_PRICE_HINTS:
        el = soup.find(tag, attrs=attrs)
        if el:
            val = el.get("content") or el.get_text(" ", strip=True)
            cur = _first_currency(val)
            if cur:
                return cur

    # site-specific selectors
    for host, selectors in SITE_PRICE_SELECTORS.items():
        if host in domain:
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    cur = _first_currency(el.get_text(" ", strip=True))
                    if cur:
                        return cur

    # generic scan
    text = soup.get_text(" ", strip=True)
    return _first_currency(text)

def extract_price_from_url(url, timeout=8):
    try:
        res = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if res.status_code != 200 or "text/html" not in res.headers.get("Content-Type", ""):
            return "Price not found"
        price = extract_price_from_html(url, res.text)
        return price or "Price not found"
    except Exception:
        return "Error fetching"

# -----------------------------
# Search engines (Yahoo removed, expanded list)
# -----------------------------
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
    "mojeek": "https://www.mojeek.com/search?q={query}",
    "ecosia": "https://www.ecosia.org/search?q={query}",
    "startpage": "https://www.startpage.com/do/dsearch?query={query}",
    "swisscows": "https://swisscows.com/web?query={query}",
    "metager": "https://metager.org/meta/meta.ger3?eingabe={query}",
    "yep": "https://yep.com/web?q={query}"
}

# -----------------------------
# Shopping allow/block rules
# -----------------------------
ALLOW_DOMAINS = {
    # India-first marketplaces & retailers
    "amazon.in", "flipkart.com", "croma.com", "reliancedigital.in", "tatacliq.com",
    "vijaysales.com", "snapdeal.com", "moglix.com", "shopclues.com", "paytmmall.com",
    # Global marketplaces
    "ebay.in", "ebay.com", "aliexpress.com"
}
BLOCKED_DOMAINS = {
    "news", "blog", "wikipedia", "youtube", "reddit", "facebook", "twitter",
    "instagram", "quora", "medium", "x.com", "linkedin", "pinterest", "gov"
}
BLOCKED_EXT = (".pdf", ".doc", ".docx", ".ppt", ".xls", ".zip", ".rar")
PATH_HINTS = {"shop", "store", "buy", "product", "products", "cart", "checkout", "deal", "p/"}

def is_shopping_url(url):
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https"):
            return False
        if any(url.lower().endswith(ext) for ext in BLOCKED_EXT):
            return False
        host = u.netloc.lower()
        if any(b in host for b in BLOCKED_DOMAINS):
            return False
        # strong allow
        if any(h in host for h in ALLOW_DOMAINS):
            return True
        # path/query hints
        path_q = (u.path + "?" + (u.query or "")).lower()
        if any(h in path_q for h in PATH_HINTS):
            return True
        return False
    except Exception:
        return False

def clean_outgoing_url(href):
    """
    Unwrap common SERP redirect patterns.
    """
    if not href:
        return None

    # Direct http(s)
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("&rut=")[0]

    # DDG style /l/?uddg=
    if "uddg=" in href:
        try:
            return unquote(href.split("uddg=")[-1].split("&")[0])
        except Exception:
            pass

    # Generic /url?url= /url?q= /redir?url=  /aclk?u=
    if href.startswith("/") or href.startswith("?"):
        try:
            # fabricate absolute for parsing
            p = urlparse("https://example.com" + href)
            qs = parse_qs(p.query)
            for key in ("url", "q", "u", "ru", "target"):
                if key in qs:
                    candidate = qs[key][0]
                    if candidate.startswith("http"):
                        return unquote(candidate)
        except Exception:
            pass

    return None

def extract_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = clean_outgoing_url(a["href"])
        if not href:
            continue
        title = a.get_text(" ", strip=True)[:200]
        links.append((href, title))
    return links

def normalize_key(url):
    try:
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}{u.path}"
        return base.rstrip("/")
    except Exception:
        return url

def fetch_html(url, timeout=10):
    try:
        r = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code != 200:
            return None
        # basic content-type check
        ctype = r.headers.get("Content-Type", "")
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return None
        return r.text
    except Exception:
        return None

# -----------------------------
# API routes
# -----------------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Shopping-First, Multi-Engine, Resilient) is running!"

# ✅ Health check endpoint for UptimeRobot
@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json or {}
    query = (data.get('query') or "").strip()
    if not query:
        return jsonify({'error': 'Query required'}), 400

    # India-shopping focus
    search_query = query if "buy in india" in query.lower() else f"{query} Buy in India"
    encoded = quote_plus(search_query)

    TARGET_MIN = 12          # aim for at least this many
    MAX_COLLECT = 40         # hard cap
    PER_ENGINE_LIMIT = 15    # per-engine soft cap
    SLEEP_BETWEEN = 0.7      # throttle to avoid bans

    results = []
    seen = set()

    # Collect from ALL engines (ordered by typical quality for shopping)
    ordered_engines = [
        "bing", "duckduckgo", "brave", "qwant", "mojeek", "ecosia", "startpage", "swisscows", "metager", "yep"
    ]

    for name in ordered_engines:
        engine_url = SEARCH_ENGINES.get(name).format(query=encoded)
        html = fetch_html(engine_url)
        if not html:
            time.sleep(SLEEP_BETWEEN)
            continue

        added_this_engine = 0
        for href, title in extract_links(html):
            if not is_shopping_url(href):
                continue

            key = normalize_key(href)
            if key in seen:
                continue

            seen.add(key)
            results.append({"title": title or name, "url": href})
            added_this_engine += 1

            if len(results) >= MAX_COLLECT or added_this_engine >= PER_ENGINE_LIMIT:
                break

        # move to next engine regardless, but stop if we already have plenty
        time.sleep(SLEEP_BETWEEN)
        if len(results) >= TARGET_MIN:
            # keep going lightly to add diversity but don't over-fetch
            continue

    # If still too few, allow more permissive pass (relax path hints but keep blocklists)
    if len(results) < TARGET_MIN:
        relaxed = []
        for name in ordered_engines:
            engine_url = SEARCH_ENGINES.get(name).format(query=encoded)
            html = fetch_html(engine_url)
            if not html:
                continue
            for href, title in extract_links(html):
                try:
                    u = urlparse(href)
                    if u.scheme not in ("http", "https"):
                        continue
                    host = u.netloc.lower()
                    if any(b in host for b in BLOCKED_DOMAINS):
                        continue
                    if host.endswith(".gov") or host.endswith(".edu"):
                        continue
                    key = normalize_key(href)
                    if key in seen:
                        continue
                    seen.add(key)
                    relaxed.append({"title": title or name, "url": href})
                    if len(results) + len(relaxed) >= TARGET_MIN:
                        break
                except Exception:
                    continue
            if len(results) + len(relaxed) >= TARGET_MIN:
                break
        results.extend(relaxed)

    # Price fetch concurrently for top N
    top = results[:25]
    if top:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(extract_price_from_url, item["url"]): i for i, item in enumerate(top)}
            for fut in concurrent.futures.as_completed(futs):
                idx = futs[fut]
                price = None
                try:
                    price = fut.result()
                except Exception:
                    price = None
                if price and price not in ("Price not found", "Error fetching"):
                    top[idx]["price"] = price

    final = top[:20] if top else [{"error": "No shopping results found"}]
    return jsonify({
        "product": search_query,
        "results": final
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```0
