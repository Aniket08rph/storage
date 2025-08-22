from flask import Flask, request, jsonify
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, quote_plus
import re, time, random, concurrent.futures

app = Flask(__name__)

# --------------------
# Robust session
# --------------------
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

# --------------------
# Headers
# --------------------
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
        "Connection": "close",
    }

# --------------------
# Price extraction
# --------------------
CURRENCY_PATTERNS = [
    r'₹\s?[\d,]+(?:\.\d+)?',
    r'Rs.?\s?[\d,]+(?:\.\d+)?',
    r'\$\s?[\d,]+(?:\.\d+)?'
]

SITE_SELECTORS = {
    "amazon.in": [".a-price .a-offscreen", "#corePriceDisplay_desktop_feature_div .a-offscreen"],
    "flipkart.com": ["._30jeq3", "._1vC4OE"],
    "croma.com": [".pdp-price .amount"],
    "reliancedigital.in": [".pdp__finalPrice", ".price"],
    "tatacliq.com": [".price__value"],
    "snapdeal.com": [".payBlkBig"],
}

def _first_currency(text):
    if not text:
        return None
    for p in CURRENCY_PATTERNS:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None

def extract_price_from_html(url, html):
    domain = urlparse(url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")

    # Site-specific selectors
    for host, selectors in SITE_SELECTORS.items():
        if host in domain:
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    cur = _first_currency(el.get_text(" ", strip=True))
                    if cur:
                        return cur

    # Meta tags
    metas = soup.find_all("meta")
    for m in metas:
        if m.get("property", "").lower().endswith("price:amount") or m.get("itemprop") == "price":
            val = m.get("content") or m.get("value") or ""
            cur = _first_currency(val)
            if cur:
                return cur

    # Fallback
    return _first_currency(soup.get_text(" ", strip=True))

def extract_price_from_url(url, timeout=7):
    try:
        r = SESSION.get(url, headers=default_headers(), timeout=timeout)
        if r.status_code != 200:
            return None
        if "text/html" not in r.headers.get("Content-Type", ""):
            return None
        return extract_price_from_html(url, r.text)
    except Exception:
        return None

# --------------------
# Search engines
# --------------------
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}",
}

# --------------------
# Direct shopping sites search pages
# --------------------
SHOPPING_SITES = {
    "amazon.in": "https://www.amazon.in/s?k={query}",
    "flipkart.com": "https://www.flipkart.com/search?q={query}",
    "croma.com": "https://www.croma.com/search/?text={query}",
    "reliancedigital.in": "https://www.reliancedigital.in/search?q={query}",
    "tatacliq.com": "https://www.tatacliq.com/search/?searchCategory=all&text={query}",
    "snapdeal.com": "https://www.snapdeal.com/search?keyword={query}",
}

# --------------------
# Utils
# --------------------
BLOCKED_DOMAINS = ["wikipedia", "youtube", "facebook", "twitter", "instagram", "reddit", "medium"]
PATH_HINTS = ["product", "p/", "shop", "store", "buy", "product-category"]
BLOCKED_EXT = (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".svg")

def clean_outgoing_url(href):
    if not href: return None
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("&rut=")[0]
    if "uddg=" in href:
        try: return unquote(href.split("uddg=")[-1].split("&")[0])
        except: return None
    if href.startswith("/"):
        try:
            if "q=" in href:
                q = href.split("q=")[-1].split("&")[0]
                if q.startswith("http"):
                    return unquote(q)
        except: return None
    return None

def normalize_key(url):
    try:
        u = urlparse(url)
        return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/")
    except: return url

def is_valid_shopping_url(url):
    try:
        if not url.startswith("http"): return False
        if url.lower().endswith(BLOCKED_EXT): return False
        host = urlparse(url).netloc.lower()
        if any(b in host for b in BLOCKED_DOMAINS): return False
        path_q = (urlparse(url).path + "?" + (urlparse(url).query or "")).lower()
        if any(h in host for h in ["amazon.in", "flipkart.com", "croma.com", "reliancedigital.in", "tatacliq.com", "snapdeal.com"]):
            return True
        if any(hint in path_q for hint in PATH_HINTS): return True
        return False
    except: return False

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
    except Exception: return None

# --------------------
# Flask Endpoints
# --------------------
@app.route('/')
def home():
    return "🔥 CreativeScraper (Upgraded + Direct Shopping Sites) is running!"

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max_results", 10))
    if not query:
        return jsonify({"error": "Query required"}), 400

    search_query = query if "buy in india" in query.lower() else f"{query} Buy in India"
    encoded = quote_plus(search_query)

    candidates, seen_keys = [], set()
    per_engine_limit = 12
    sleep_between = 0.8 + random.random()*0.5  # jitter

    # 1) Direct shopping site search pages
    for site, tmpl in SHOPPING_SITES.items():
        url = tmpl.format(query=encoded)
        html = fetch_html(url)
        if not html: continue
        links = extract_links_from_html(html)
        for href, title in links:
            if not is_valid_shopping_url(href): continue
            key = normalize_key(href)
            if key in seen_keys: continue
            seen_keys.add(key)
            candidates.append({"title": title or site, "url": href, "source": site})
        time.sleep(sleep_between)

    # 2) Search engines fallback
    for engine_name, tmpl in SEARCH_ENGINES.items():
        try:
            url = tmpl.format(query=encoded)
            html = fetch_html(url)
            if not html:
                time.sleep(sleep_between)
                continue
            links = extract_links_from_html(html)
            added = 0
            for href, title in links:
                if not is_valid_shopping_url(href): continue
                key = normalize_key(href)
                if key in seen_keys: continue
                seen_keys.add(key)
                candidates.append({"title": title or engine_name, "url": href, "source": engine_name})
                added += 1
                if added >= per_engine_limit or len(candidates) >= 60: break
            time.sleep(sleep_between)
        except: continue

    # 3) Fetch prices concurrently
    top = candidates[:min(len(candidates), 30)]
    if top:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(extract_price_from_url, item["url"]): i for i, item in enumerate(top)}
            for fut in concurrent.futures.as_completed(futs):
                i = futs[fut]
                try: price = fut.result()
                except: price = None
                if price: top[i]["price"] = price

    # 4) Ranking
    def rank_key(it):
        host = urlparse(it["url"]).netloc.lower()
        score = 0
        if it.get("price"): score += 100
        if "amazon.in" in host: score += 50
        if "flipkart.com" in host: score += 45
        if any(x in host for x in ["croma.com", "reliancedigital.in", "tatacliq.com", "snapdeal.com"]):
            score += 30
        return -score

    top.sort(key=rank_key)
    final = top[:max_results]

    out = []
    for item in final:
        out_item = {
            "title": item.get("title"),
            "url": item.get("url"),
            "price": item.get("price") or None,
            "source": item.get("source")
        }
        out.append(out_item)

    if not out:
        out = [{"error": "No shopping results found"}]

    return jsonify({"product": search_query, "results": out})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
