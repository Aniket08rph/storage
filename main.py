# app.py
from flask import Flask, request, jsonify
import os, re, time, random, concurrent.futures, threading
from urllib.parse import urlparse, quote_plus, unquote
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

app = Flask(__name__)

# =========================
# Config
# =========================
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
REQ_TIMEOUT = int(os.getenv("REQ_TIMEOUT", "10"))
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "10"))
PRICE_TIMEOUT = int(os.getenv("PRICE_TIMEOUT", "10"))
PER_ENGINE_LIMIT = int(os.getenv("PER_ENGINE_LIMIT", "12"))
CANDIDATE_LIMIT = int(os.getenv("CANDIDATE_LIMIT", "60"))
MAX_PRICE_FETCH = int(os.getenv("MAX_PRICE_FETCH", "35"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "120"))  # seconds
SLEEP_BETWEEN_ENGINES = float(os.getenv("SLEEP_BETWEEN_ENGINES", "0.6"))

# Optional proxy: set HTTP(S)_PROXY or a provider URL in PROXY_URL
PROXY_URL = os.getenv("PROXY_URL", "").strip()
USE_PROXIES = bool(PROXY_URL)

# =========================
# Identity / Headers
# =========================
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]
ACCEPTS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html;q=0.9,*/*;q=0.8",
]

def default_headers():
    return {
        "User-Agent": random.choice(UAS),
        "Accept": random.choice(ACCEPTS),
        "Accept-Language": random.choice(["en-IN,en;q=0.9","en-US,en;q=0.9","en-GB,en;q=0.9"]),
        "Connection": "close",
        "DNT": random.choice(["1","0"]),
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if USE_PROXIES:
        s.proxies.update({"http": PROXY_URL, "https": PROXY_URL})
    return s

# Per-domain session reuse (cookies help stealth)
_sessions_lock = threading.Lock()
_sessions = {}
def get_domain_session(domain):
    with _sessions_lock:
        if domain not in _sessions:
            _sessions[domain] = make_session()
        return _sessions[domain]

# =========================
# Utilities
# =========================
def jitter(min_s=0.25, max_s=0.9):
    time.sleep(random.uniform(min_s, max_s))

def fetch_html(url, timeout=REQ_TIMEOUT, referer=None):
    try:
        domain = urlparse(url).netloc.lower()
        s = get_domain_session(domain)
        headers = default_headers()
        if referer:
            headers["Referer"] = referer
        r = s.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        ctype = r.headers.get("Content-Type", "")
        if "text/html" not in ctype:
            return None
        return r.text
    except Exception:
        return None

def clean_outgoing_url(href):
    if not href:
        return None
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("&rut=")[0]
    if "uddg=" in href:
        try:
            return unquote(href.split("uddg=")[-1].split("&")[0])
        except Exception:
            return None
    if href.startswith("/"):
        try:
            if "q=" in href:
                q = href.split("q=")[-1].split("&")[0]
                if q.startswith("http"):
                    return unquote(q)
        except Exception:
            return None
    return None

def extract_links_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        url = clean_outgoing_url(a["href"])
        if not url:
            continue
        title = a.get_text(" ", strip=True)[:200]
        out.append((url, title))
    return out

def normalize_key(url):
    try:
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}{u.path}"
        return base.rstrip("/")
    except Exception:
        return url

# =========================
# Price extraction
# =========================
CURRENCY_PATTERNS = [
    r'₹\s?[\d,]+(?:\.\d+)?',
    r'Rs\.?\s?[\d,]+(?:\.\d+)?',
    r'\$\s?[\d,]+(?:\.\d+)?'
]

SITE_SELECTORS = {
    "amazon.in": [
        ".a-price .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#apex_desktop .a-offscreen",
    ],
    "flipkart.com": [
        "._30jeq3._16Jk6d",  # PDP
        "div._30jeq3",       # SRP
    ],
    "croma.com": [
        ".pdp-price .amount",
        "[data-testid=price] .amount",
    ],
    "reliancedigital.in": [
        ".pdp__finalPrice",
        ".pdp__offerPrice",
        ".price",
    ],
    "tatacliq.com": [
        ".price__value",
        "[data-test='pdp-product-price']",
    ]
}

def _first_currency(text):
    if not text:
        return None
    for p in CURRENCY_PATTERNS:
        m = re.search(p, text)
        if m:
            return m.group(0).strip()
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

    # Schema / meta tags
    for m in soup.find_all("meta"):
        prop = (m.get("property") or m.get("itemprop") or "").lower()
        if "price" in prop or prop.endswith("price:amount"):
            val = m.get("content") or m.get("value") or ""
            cur = _first_currency(val)
            if cur:
                return cur

    # Fallback: nearest currency in page text
    return _first_currency(soup.get_text(" ", strip=True))

def extract_price_from_url(url, timeout=PRICE_TIMEOUT):
    try:
        html = fetch_html(url, timeout=timeout)
        if not html:
            return None
        return extract_price_from_html(url, html)
    except Exception:
        return None

# =========================
# Direct site search (SRP → PDP)
# =========================
DIRECT_SITES = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "croma": "https://www.croma.com/search/?text={q}",
    "reliancedigital": "https://www.reliancedigital.in/search?q={q}",
    "tatacliq": "https://www.tatacliq.com/search/?searchCategory=all&text={q}",
}

def parse_srp_for_links(domain, html, limit=3):
    """Extract product links from search result pages (best-effort; sites change often)."""
    soup = BeautifulSoup(html, "html.parser")
    links = []

    if "amazon.in" in domain:
        for a in soup.select("a.a-link-normal.s-no-outline, a.a-link-normal.s-underline-text"):
            href = a.get("href")
            if href and "/dp/" in href:
                links.append("https://www.amazon.in" + href.split("?")[0])
            if len(links) >= limit:
                break

    elif "flipkart.com" in domain:
        for a in soup.select("a._1fQZEK, a._2UzuFa, a.KtPHx3"):
            href = a.get("href")
            if href and href.startswith("/"):
                links.append("https://www.flipkart.com" + href.split("?")[0])
            if len(links) >= limit:
                break

    elif "croma.com" in domain:
        for a in soup.select("a.product-title, a.product-item__primary-action"):
            href = a.get("href")
            if href and href.startswith("/"):
                links.append("https://www.croma.com" + href.split("?")[0])
            if len(links) >= limit:
                break

    elif "reliancedigital.in" in domain:
        for a in soup.select("a.pl__item__info__link, a[href*='/product/']"):
            href = a.get("href")
            if href and href.startswith("/"):
                links.append("https://www.reliancedigital.in" + href.split("?")[0])
            if len(links) >= limit:
                break

    elif "tatacliq.com" in domain:
        for a in soup.select("a[href*='/p-']"):
            href = a.get("href")
            if href and href.startswith("/"):
                links.append("https://www.tatacliq.com" + href.split("?")[0])
            if len(links) >= limit:
                break

    # Generic fallback: take first few product-like anchors
    if not links:
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                full = f"https://{domain}{href.split('?')[0]}"
            elif href.startswith("http"):
                full = href.split("?")[0]
            else:
                continue
            if any(x in full.lower() for x in ["/p/", "/dp/", "/product", "/buy"]):
                links.append(full)
            if len(links) >= limit:
                break

    return links

def fetch_direct_sites(query, per_site=3):
    out = []
    for name, tmpl in DIRECT_SITES.items():
        try:
            srp = tmpl.format(q=quote_plus(query))
            domain = urlparse(srp).netloc
            html = fetch_html(srp, timeout=SEARCH_TIMEOUT, referer=f"https://{domain}/")
            if not html:
                continue
            jitter()
            pdp_links = parse_srp_for_links(domain, html, limit=per_site)
            for link in pdp_links:
                price = extract_price_from_url(link)
                if price:
                    out.append({
                        "title": f"{query} on {name}",
                        "url": link,
                        "price": price,
                        "source": name
                    })
                jitter(0.25, 0.7)
        except Exception:
            continue
    return out

# =========================
# Search engines fallback
# =========================
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "brave": "https://search.brave.com/search?q={query}",
    "qwant": "https://lite.qwant.com/?q={query}"
}
BLOCKED_DOMAINS = ["wikipedia", "youtube", "facebook", "twitter", "instagram", "reddit", "medium"]
PATH_HINTS = ["product", "p/", "shop", "store", "buy", "product-category", "cart", "checkout"]
BLOCKED_EXT = (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".svg")

def is_valid_shopping_url(url):
    try:
        if not url.startswith("http"):
            return False
        if url.lower().endswith(BLOCKED_EXT):
            return False
        host = urlparse(url).netloc.lower()
        if any(b in host for b in BLOCKED_DOMAINS):
            return False
        path_q = (urlparse(url).path + "?" + (urlparse(url).query or "")).lower()
        if any(h in host for h in ["amazon.in","flipkart.com","croma.com","reliancedigital.in","tatacliq.com","snapdeal.com"]):
            return True
        if any(hint in path_q for hint in PATH_HINTS):
            return True
        return False
    except Exception:
        return False

def fetch_from_search_engines(query, max_candidates=CANDIDATE_LIMIT):
    encoded = quote_plus(query)
    candidates = []
    seen_keys = set()

    for engine_name, tmpl in SEARCH_ENGINES.items():
        try:
            url = tmpl.format(query=encoded)
            html = fetch_html(url, timeout=SEARCH_TIMEOUT)
            if not html:
                jitter()
                continue
            links = extract_links_from_html(html)
            added = 0
            for href, title in links:
                if not href or not is_valid_shopping_url(href):
                    continue
                key = normalize_key(href)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append({"title": title or engine_name, "url": href, "source": engine_name})
                added += 1
                if added >= PER_ENGINE_LIMIT or len(candidates) >= max_candidates:
                    break
            jitter(0.25, 0.8)
        except Exception:
            continue

    return candidates

# =========================
# Ranking / Dedupe
# =========================
def rank_key(it):
    host = urlparse(it["url"]).netloc.lower()
    score = 0
    if it.get("price"):
        score += 100
    if "amazon.in" in host:
        score += 50
    if "flipkart.com" in host:
        score += 45
    if any(x in host for x in ["croma.com","reliancedigital.in","tatacliq.com"]):
        score += 30
    return -score

def dedupe_keep_best(items):
    best = {}
    for it in items:
        key = normalize_key(it["url"])
        if key not in best:
            best[key] = it
        else:
            # keep the one with price or higher score
            if (not best[key].get("price")) and it.get("price"):
                best[key] = it
            else:
                if rank_key(it) < rank_key(best[key]):
                    best[key] = it
    return list(best.values())

# =========================
# Tiny TTL cache
# =========================
_cache_lock = threading.Lock()
_cache = {}  # key: query_lower -> (timestamp, payload)

def cache_get(q):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(q)
        if not hit:
            return None
        ts, payload = hit
        if now - ts > CACHE_TTL:
            _cache.pop(q, None)
            return None
        return payload

def cache_set(q, payload):
    with _cache_lock:
        _cache[q] = (time.time(), payload)

# =========================
# Routes
# =========================
@app.route("/")
def home():
    return "🔥 AI Shopping Scraper (Direct Sites + Search Fallback + Stealth) is running!"

@app.route("/ping")
def ping():
    return jsonify({"status": "ok"}), 200

@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max_results", 10))
    india_focus = data.get("india_focus", True)

    if not query:
        return jsonify({"error": "Query required"}), 400

    # Optional India focus
    search_query = query if (not india_focus or "buy in india" in query.lower()) else f"{query} Buy in India"
    qkey = f"{search_query.lower()}|{max_results}"

    # Cache first
    cached = cache_get(qkey)
    if cached:
        return jsonify(cached)

    results = []

    # 1) Direct shopping sites (concurrently)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut = ex.submit(fetch_direct_sites, search_query, 3)
        direct_results = fut.result()
        results.extend(direct_results)

    # 2) If not enough, search engines → collect candidates → fetch price concurrently
    if len(results) < max_results:
        candidates = fetch_from_search_engines(search_query, max_candidates=CANDIDATE_LIMIT)

        # Fetch prices concurrently for top candidates
        top = candidates[:min(len(candidates), MAX_PRICE_FETCH)]
        if top:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                future_map = {ex.submit(extract_price_from_url, item["url"]): i for i, item in enumerate(top)}
                for fut in concurrent.futures.as_completed(future_map):
                    i = future_map[fut]
                    try:
                        price = fut.result()
                    except Exception:
                        price = None
                    if price:
                        top[i]["price"] = price
                    jitter(0.1, 0.4)
            results.extend(top)

    # 3) Dedupe + rank + trim
    results = dedupe_keep_best(results)
    results.sort(key=rank_key)
    final = results[:max_results]

    if not final:
        final = [{"error": "No shopping results found"}]

    payload = {"product": search_query, "results": final}
    cache_set(qkey, payload)
    return jsonify(payload)

# =========================
# Run
# =========================
if __name__ == "__main__":
    # For Render, use PORT env if provided
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
