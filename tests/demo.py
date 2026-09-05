"""Web widget demo available only in the test stack."""
import html
import os

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from bridge.app import create_app


def create_demo_app(*, public_url=None, website_token=None, **kwargs):
    app = create_app(**kwargs)
    public_url = public_url or os.getenv("CHATWOOT_PUBLIC_URL", "http://localhost:3000")
    website_token = website_token or os.getenv("CHATWOOT_WEBSITE_TOKEN", "")

    @app.get("/demo", response_class=HTMLResponse)
    async def demo_page() -> HTMLResponse:
        if not website_token:
            raise HTTPException(status_code=503, detail="CHATWOOT_WEBSITE_TOKEN is not configured")
        base_url = html.escape(public_url, quote=True)
        token = html.escape(website_token, quote=True)
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Hermes Chatwoot test</title></head>
<body><h1>Hermes / Chatwoot test chat</h1>
<p>Open the widget in the bottom-right corner and send a message.</p>
<script>
window.chatwootSettings = {{ position: "right", type: "standard" }};
(function(d,t) {{
  var BASE_URL = "{base_url}";
  var g = d.createElement(t), s = d.getElementsByTagName(t)[0];
  g.src = "{base_url}/packs/js/sdk.js";
  g.defer = true; g.async = true;
  s.parentNode.insertBefore(g,s);
  g.onload = function() {{ window.chatwootSDK.run({{ websiteToken: "{token}", baseUrl: BASE_URL }}); }};
}})(document,"script");
</script></body></html>"""
        return HTMLResponse(body)

    return app


app = create_demo_app()
