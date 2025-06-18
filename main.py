from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re

app = Flask(__name__)

# Extract price intelligently from known e-commerce sites
def extract_price_from_url(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
        }
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Flipkart
        if "flipkart.com" in url:
            price_tag = soup.find("div", {"class": "_30jeq3"})
            if price_tag:
                return price_tag.text.strip()

        # Amazon
        if "amazon." in url:
            tag = soup.find(id="priceblock_ourprice") or soup.find(id="priceblock_dealprice")
            if tag:
                return tag.text.strip()

        # Croma
        if "croma.com" in url:
            tag = soup.find("span", {"class": "amount"})
            if tag:
                return tag.text.strip()

        # Reliance Digital
        if "reliancedigital.in" in url:
            tag = soup.find("span", {"class": "pdp__offerPrice"})
            if tag:
                return tag.text.strip()

        # Fallback: Search ₹ price using regex
        price_text = soup.get_text()
        prices = re.findall(r'₹\s?[0-9,]+', price_text)
        if prices:
            return prices[0]

        return "Price not found"
    except:
        return "Error fetching"

@app.route('/')
def home():
    return "🔥 CreativeScraper (Smart Phase) is Live"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)"
    }

    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    res = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1])
            clean_url = full_url.split("&rut=")[0]
            text = a.get_text().strip()

            price = extract_price_from_url(clean_url)

            if price != "Price not found" and price != "Error fetching":
                results.append({
                    "title": text,
                    "url": clean_url,
                    "price": price
                })

            if len(results) >= 5:
                break

    return jsonify({
        "product": query,
        "results": results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
