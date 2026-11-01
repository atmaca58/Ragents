from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from urllib.parse import urlsplit


def management_app(server: MCPServer, *, remote_provider=None) -> Starlette:
    """Yerel/tünelli yönetim; SDK'nın Host/Origin korumasını açık tutar."""
    security = None
    if remote_provider is not None:
        from mcp.server.transport_security import TransportSecuritySettings
        parsed = urlsplit(remote_provider.issuer)
        security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[parsed.netloc], allowed_origins=[remote_provider.issuer, "https://chatgpt.com"])
    app = server.streamable_http_app(
        host="127.0.0.1", stateless_http=True, json_response=True,
        max_request_body_size=256 * 1024, transport_security=security,
    )
    if remote_provider is not None:
        async def pending(request):
            from ragents.storage import TaskStateError
            try:
                redirect = remote_provider.complete(request.path_params["identity"])
            except TaskStateError:
                return JSONResponse({"error": "Bağlantı talebi geçersiz veya süresi doldu."}, 400)
            if redirect:
                response = RedirectResponse(redirect, status_code=303)
            else:
                response = HTMLResponse('<!doctype html><html lang="tr"><meta charset="utf-8">'
                    '<meta http-equiv="refresh" content="3"><title>R Agents bağlantı onayı</title>'
                    '<h1>Terminal onayı bekleniyor</h1><p>Terminalde ragents approvals connections ile istemciyi, callback adresini '
                    've yetkileri inceleyin. ragents approvals approve-connection KIMLIK ile onaylayın. Bu sayfa kendiliğinden güncellenecek.</p></html>')
            response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                     "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})
            return response
        app.routes.append(Route("/oauth/pending/{identity}", pending))
    return app
