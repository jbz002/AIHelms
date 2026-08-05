"""resolve_platform_public_url 端口处理回归测试。

历史 bug：浏览器用非 80 端口访问 web 端时，下载 URL 仍被拼成 80 端口导致连接拒绝。
"""

from types import SimpleNamespace

from core import public_urls


def _request(host: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"host": host})


def _request_with_forwarded(host: str, forwarded_host: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"host": host, "x-forwarded-host": forwarded_host})


def test_platform_url_preserves_browser_port(monkeypatch):
    """Host 头带非 80 端口时，URL 必须保留该端口。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    url = public_urls.resolve_platform_public_url(_request("192.168.125.23:30710"))
    assert url == "http://192.168.125.23:30710"


def test_platform_url_host_without_port_uses_web_port(monkeypatch):
    """Host 头无端口（默认端口或反代剥端口）时，按 WEB_PORT 配置补。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 30710)
    url = public_urls.resolve_platform_public_url(_request("192.168.125.23"))
    assert url == "http://192.168.125.23:30710"


def test_platform_url_web_port_80_omitted(monkeypatch):
    """WEB_PORT=80 且 Host 无端口时省略端口。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    url = public_urls.resolve_platform_public_url(_request("192.168.125.23"))
    assert url == "http://192.168.125.23"


def test_platform_url_loopback_falls_back(monkeypatch):
    """loopback 主机名不可用，走回退；容器内回退到配置值。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    monkeypatch.setattr(
        public_urls.settings, "platform_public_url", "https://cfg.example"
    )
    monkeypatch.setattr(public_urls.os.path, "exists", lambda _: True)  # 模拟容器内
    url = public_urls.resolve_platform_public_url(_request("127.0.0.1:8000"))
    assert url == "https://cfg.example"


def test_litellm_url_uses_fixed_port_not_browser_port(monkeypatch):
    """LiteLLM 独立端口，不复用浏览器端口。"""
    monkeypatch.setattr(public_urls.settings, "litellm_port", 4000)
    url = public_urls.resolve_litellm_public_url(_request("192.168.125.23:30710"))
    assert url == "http://192.168.125.23:4000"


def test_platform_url_ipv6_with_port():
    url = public_urls.resolve_platform_public_url(_request("[2001:db8::1]:8080"))
    assert url == "http://[2001:db8::1]:8080"


def test_platform_url_prefers_forwarded_host_with_port(monkeypatch):
    """nginx 转发场景：X-Forwarded-Host（$http_host，含端口）优先于被剥端口的 Host。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    req = _request_with_forwarded("192.168.125.23", "192.168.125.23:30700")
    url = public_urls.resolve_platform_public_url(req)
    assert url == "http://192.168.125.23:30700"


def test_platform_url_loopback_host_keeps_browser_port(monkeypatch):
    """localhost:4002 访问时 host 换 LAN IP，但浏览器端口必须保留（不再回退成 80）。

    复现：开发态从 http://localhost:4002 打开 web 端，旧实现把 loopback 整条丢弃、端口随
    之丢失，回退用 WEB_PORT=80 生成无端口 URL，下载被拒。
    """
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    monkeypatch.setattr(public_urls, "_fallback_host", lambda: "192.168.125.23")
    url = public_urls.resolve_platform_public_url(_request("localhost:4002"))
    assert url == "http://192.168.125.23:4002"


def test_platform_url_ipv6_loopback_keeps_browser_port(monkeypatch):
    """[::1]:4002 同理：host 换 LAN IP，端口保留。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    monkeypatch.setattr(public_urls, "_fallback_host", lambda: "192.168.125.23")
    url = public_urls.resolve_platform_public_url(_request("[::1]:4002"))
    assert url == "http://192.168.125.23:4002"


def test_platform_url_loopback_xforwarded_keeps_browser_port(monkeypatch):
    """vite 代理：浏览器 localhost:4002 → x-forwarded-host: localhost:4002，端口保留。"""
    monkeypatch.setattr(public_urls.settings, "web_port", 80)
    monkeypatch.setattr(public_urls, "_fallback_host", lambda: "192.168.125.23")
    req = _request_with_forwarded("localhost:8000", "localhost:4002")
    url = public_urls.resolve_platform_public_url(req)
    assert url == "http://192.168.125.23:4002"
