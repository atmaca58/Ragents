"""İzin verilmiş, sabit resmi MCP uçlarından anahtarsız arama."""
import json
import re
import uuid

from ragents.web_tools import WebAccessError


KEYLESS_PROVIDERS = ('exa_free', 'parallel_free', 'keenable_free')
ENDPOINTS = {
    'exa_free': ('https://mcp.exa.ai/mcp', 'web_search_exa'),
    'parallel_free': ('https://search.parallel.ai/mcp', 'web_search'),
    'keenable_free': ('https://api.keenable.ai/mcp-public', 'search_web_pages'),
}
_SESSION = uuid.uuid4().hex


def parse_mcp_response(body):
    text = body.decode('utf-8')
    if text.lstrip().startswith('{'):
        envelopes = [json.loads(text)]
    else:
        frames, current = [], []
        for line in re.split(r'\r\n|\r|\n', text) + ['']:
            if not line:
                if current:
                    frames.append('\n'.join(current))
                    current = []
            elif line.startswith('data:'):
                current.append(line[5:].lstrip(' '))
        envelopes = [json.loads(frame) for frame in frames if frame != '[DONE]']
    reply = next((item for item in envelopes if isinstance(item, dict) and item.get('id') == 1), None)
    if reply is None or reply.get('error'):
        raise WebAccessError('Anahtarsız arama MCP isteği reddedildi veya yanıt tanınmadı.')
    result = reply.get('result')
    if not isinstance(result, dict) or result.get('isError'):
        raise WebAccessError('Anahtarsız arama aracı erişim/kota hatası bildirdi.')
    if isinstance(result.get('structuredContent'), dict):
        return result['structuredContent']
    texts = [item['text'] for item in result.get('content', [])
             if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str)]
    if not texts:
        raise WebAccessError('Anahtarsız arama aracı içerik döndürmedi.')
    joined = '\n'.join(texts)
    try:
        return json.loads(joined)
    except ValueError:
        return joined


def exa_rows(text):
    rows, current, field = [], None, None
    for line in text.split('\n'):
        label, separator, value = line.strip().partition(':')
        if separator and label in ('Title', 'URL', 'Published', 'Published Date', 'Highlights', 'Content', 'Text'):
            if label == 'Title':
                if current:
                    rows.append(current)
                current = {'title': value.strip(), 'content': ''}
            if current is not None:
                field = {'URL': 'url', 'Published': 'published_date', 'Published Date': 'published_date',
                         'Highlights': 'content', 'Content': 'content', 'Text': 'content', 'Title': 'title'}[label]
                current[field] = value.strip()
        elif current is not None and field == 'content' and line.strip() != '---':
            current['content'] += '\n' + line
    if current:
        rows.append(current)
    if not rows or not any(row.get('url') for row in rows):
        raise WebAccessError('Exa sonuç biçimi tanınmadı.')
    return rows


def keyless_search(client, provider, query, count):
    url, tool = ENDPOINTS[provider]
    arguments = {
        'exa_free': {'query': query, 'numResults': count},
        'parallel_free': {'objective': query, 'search_queries': [query], 'session_id': _SESSION},
        'keenable_free': {'query': query, 'max_results': count, 'output_format': 'json'},
    }[provider]
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}}
    try:
        _, response = client.request(url, method='POST',
            headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'},
            body=json.dumps(payload).encode('utf-8'))
        if response.status != 200:
            raise WebAccessError('Anahtarsız arama tamamlanmış yanıt vermedi.')
        data = parse_mcp_response(response.body)
        if provider == 'exa_free' and isinstance(data, str):
            return exa_rows(data)[:count]
        if not isinstance(data, dict) or data.get('success') is False or data.get('error'):
            raise WebAccessError('Anahtarsız sağlayıcı geçerli arama sonucu vermedi.')
        container = data.get('data', data)
        if isinstance(container, list):
            rows = container
        elif isinstance(container, dict):
            rows = container.get('results', container.get('web'))
        else:
            rows = None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise WebAccessError('Anahtarsız arama sonuç şeması tanınmadı.')
        return [{**row, 'content': row.get('content') or row.get('snippet') or row.get('description')
                 or '\n'.join(str(value) for value in row.get('excerpts', []))} for row in rows[:count]]
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise WebAccessError('Anahtarsız arama yanıtı beklenen biçimde değil.') from None
