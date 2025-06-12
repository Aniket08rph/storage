from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper Phase 2 Live!"

def extract_price_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Amazon India
        if "amazon.in" in url:
            price = soup.find('span', {'id': 'priceblock_ourprice'}) \
                or soup.find('span', {'id': 'priceblock_dealprice'}) \
                or soup.find('span', {'class': 'a-price-whole'})
            if price:
                return price.get_text(strip=True)

        # Flipkart
        if "flipkart.com" in url:
            price = soup.find('div', {'class': '_30jeq3 _16Jk6d'})
            if price:
                return price.get_text(strip=True)

        # Reliance Digital
        if "reliancedigital.in" in url:
            price = soup.find('span', {'class': 'pdp__offerPrice'})
            if price:
                return price.get_text(strip=True)

        # Croma
        if "croma.com" in url:
            price = soup.find('span', {'class': 'amount'})
            if price:
                return price.get_text(strip=True)

        return "Price not found"
    except Exception as e:
        return "Error fetching"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+price"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]

            text = a.get_text().strip()

            # Only continue for Indian ecommerce sites
            if any(domain in clean_url for domain in ["amazon.in", "flipkart.com", "reliancedigital.in", "croma.com"]):
                price = extract_price_from_url(clean_url)
                results.append({
                    "title": text,
                    "url": clean_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
