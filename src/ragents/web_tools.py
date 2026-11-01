"""DNS'e sabitlenmiş, özel ağları reddeden sınırlı web erişimi."""
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin


class WebAccessError(RuntimeError):
    pass


def local_web_origin(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.port is None or not 1024 <= parsed.port <= 65535):
        raise ValueError("Yerel hedef açık loopback adresi ve 1024–65535 arası port olmalıdır.")
    host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
    return f"{parsed.scheme}://{host}:{parsed.port}"


@dataclass(frozen=True)
class WebResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def resolve_addresses(host, port):
    return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


def request_pinned(url, address, method, headers, body):
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection = (http.client.HTTPSConnection(parsed.hostname, port, timeout=15, context=ssl.create_default_context())
                  if parsed.scheme == "https" else http.client.HTTPConnection(parsed.hostname, port, timeout=15))

    def connect_address(*args, **kwargs):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        stream = socket.socket(family, socket.SOCK_STREAM)
        stream.settimeout(15)
        try:
            stream.connect((address, port))
            return stream
        except BaseException:
            stream.close()
            raise

    connection._create_connection = connect_address
    try:
        connection.request(method, parsed.path or "/" if not parsed.query else (parsed.path or "/") + "?" + parsed.query,
                           body=body, headers={"User-Agent": "R-Agents/0.2", "Accept-Encoding": "identity", **headers})
        response = connection.getresponse()
        content = bytearray()
        deadline = time.monotonic() + 20
        while True:
            chunk = response.read1(65536)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024 or time.monotonic() > deadline:
                raise WebAccessError("Web yanıtı boyut veya süre sınırını aşıyor.")
        return WebResponse(response.status, {key.lower(): value for key, value in response.getheaders()}, bytes(content))
    finally:
        connection.close()


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class SafeWebClient:
    def __init__(self, *, resolver=resolve_addresses, transport=request_pinned, allowed_local=()):
        self.resolver, self.transport = resolver, transport
        self.allowed_local = {local_web_origin(value) for value in allowed_local}

    def validate(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or len(url) > 4096 or any(ord(char) < 32 for char in url)):
            raise WebAccessError("Web adresi geçersiz veya kimlik bilgisi içeriyor.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
        local_allowed = f"{parsed.scheme}://{host}:{port}" in self.allowed_local
        if port not in (80, 443) and not local_allowed:
            raise WebAccessError("Yalnız standart web portları izinli.")
        addresses = self.resolver(parsed.hostname, port)
        if not addresses:
            raise WebAccessError("Web adresi çözümlenemedi.")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if local_allowed and ip.is_loopback:
                continue
            if not ip.is_global or ip.is_multicast or ip.is_unspecified or getattr(ip, "ipv4_mapped", None):
                raise WebAccessError("Özel ağ, loopback veya kimlik metadata adresine erişim engellendi.")
        return addresses[0]

    def request(self, url, *, method="GET", headers=None, body=None, redirects=0, return_redirect=False):
        for attempt in range(redirects + 1):
            address = self.validate(url)
            try:
                response = self.transport(url, address, method, headers or {}, body)
            except (OSError, http.client.HTTPException):
                raise WebAccessError("Web bağlantısı tamamlanamadı.") from None
            if response.status in (301, 302, 303, 307, 308):
                if return_redirect:
                    target = urljoin(url, response.headers.get("location", ""))
                    self.validate(target)
                    if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
                        raise WebAccessError("Güvenli olmayan tarayıcı yönlendirmesi reddedildi.")
                    return url, response
                if attempt == redirects:
                    raise WebAccessError("Web yönlendirme sınırı aşıldı.")
                next_url = urljoin(url, response.headers.get("location", ""))
                if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
                    raise WebAccessError("HTTPS adresinden güvenli olmayan yönlendirme reddedildi.")
                url = next_url
                continue
            if response.status == 429:
                raise WebAccessError("Sağlayıcı kotası veya hız sınırı doldu; başka servise geçilmedi.")
            if response.status >= 400:
                raise WebAccessError(f"Web servisi isteği reddetti (HTTP {response.status}).")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise WebAccessError("Sıkıştırılmış web yanıtı kabul edilmedi.")
            return url, response

    def read_page(self, url):
        final_url, response = self.request(url, redirects=3)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in ("text/html", "text/plain", "application/json"):
            raise WebAccessError("Bu sayfanın içerik türü desteklenmiyor.")
        content = response.body.decode("utf-8", errors="replace")
        if content_type == "text/html":
            parser = PageText()
            parser.feed(content)
            content = "\n".join(parser.parts)
        return {"url": final_url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content": content[:16000], "truncated": len(content) > 16000, "untrusted_content": True}

    def json_request(self, url, *, method="GET", headers=None, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        _, response = self.request(url, method=method, headers=headers, body=body)
        try:
            return json.loads(response.body)
        except ValueError:
            raise WebAccessError("Web servisi geçerli JSON yanıtı vermedi.") from None
