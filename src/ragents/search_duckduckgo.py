"""DuckDuckGo HTML araması: anahtarsız, sınırlı ve deneysel."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from ragents.web_tools import WebAccessError


class SearchResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.mode = None
        self.tag = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get('class', '').split()
        if tag == 'a' and 'result__a' in classes:
            self.items.append({'url': attributes.get('href', ''), 'title': '', 'content': ''})
            self.mode, self.tag, self.depth = 'title', tag, 1
        elif self.items and 'result__snippet' in classes:
            self.mode, self.tag, self.depth = 'content', tag, 1
        elif self.mode and tag == self.tag:
            self.depth += 1

    def handle_data(self, data):
        if self.mode:
            self.items[-1][self.mode] += data

    def handle_endtag(self, tag):
        if self.mode and tag == self.tag:
            self.depth -= 1
            if not self.depth:
                self.mode = None


def search_duckduckgo(client, query, count):
    _, response = client.request('https://html.duckduckgo.com/html/?' + urlencode({'q': query}), redirects=2)
    html = response.body.decode('utf-8', errors='replace')
    if response.status != 200 or any(marker in html.lower() for marker in ('challenge-form', 'anomaly.js', 'anomaly-modal')):
        raise WebAccessError('DuckDuckGo erişim veya CAPTCHA sınırı; işlem durdu, başka sağlayıcıya geçilmedi.')
    if response.headers.get('content-type', '').split(';')[0].lower() != 'text/html':
        raise WebAccessError('DuckDuckGo beklenen HTML yanıtını vermedi.')
    parser = SearchResults()
    parser.feed(html)
    if not parser.items and 'no-results' not in html:
        raise WebAccessError('DuckDuckGo sonuç biçimi tanınmadı; boş sonuç başarı olarak gösterilmedi.')
    items, seen = [], set()
    for item in parser.items:
        url = urljoin('https://html.duckduckgo.com', item['url'])
        parsed = urlsplit(url)
        if parsed.hostname in ('duckduckgo.com', 'html.duckduckgo.com') and parsed.path == '/l/':
            url = parse_qs(parsed.query).get('uddg', [''])[0]
        if url in seen:
            continue
        seen.add(url)
        items.append({**item, 'url': url, 'title': item['title'].strip(), 'content': item['content'].strip()})
        if len(items) == count:
            break
    return items
