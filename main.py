from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

app = Flask(__name__)

@app.route('/')
def home():
    return "🔥 CreativeScraper Phase 2 is live!"

# Function to extract price from a product page
def extract_price_from_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Amazon.in selectors
        price = soup.find('span', {'id': 'priceblock_ourprice'}) \
            or soup.find('span', {'id': 'priceblock_dealprice'}) \
            or soup.find('span', {'class': 'a-price-whole'})

        # Flipkart selector
        if not price:
            price = soup.find('div', {'class': '_30jeq3 _16Jk6d'})

        return price.get_text(strip=True) if price else "Price not found"
    except Exception as e:
        return "Error fetching"

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+price"
    response = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "/l/?" in href and "uddg=" in href:
            full_url = unquote(href.split("uddg=")[-1]).split("&rut=")[0]
            text = a.get_text().strip()

            if any(currency in text for currency in ['₹', '$', 'price']):
                price = extract_price_from_url(full_url)
                results.append({
                    "title": text,
                    "url": full_url,
                    "price": price
                })

    return jsonify({
        "product": query,
        "results": results[:5]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
