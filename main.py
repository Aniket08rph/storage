@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'error': 'Query required'}), 400

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # Use DuckDuckGo (less blocked than Google)
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}+price"

    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    # Extract visible links with 'price' or currency
    links = []
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        if '₹' in text or 'price' in text:
            links.append(a['href'])

    return jsonify({
        "product": query,
        "results": links[:5]
    })
