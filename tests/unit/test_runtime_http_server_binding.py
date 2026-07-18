from __future__ import annotations

import socket
from http.server import ThreadingHTTPServer

from engine.runtime.server import RuntimeHTTPServer, RuntimeRequestHandler


def test_runtime_http_server_bind_does_not_require_reverse_dns(monkeypatch) -> None:
    lookups: list[str] = []

    def fail_reverse_dns(host: str) -> str:
        lookups.append(host)
        raise AssertionError("numeric loopback bind must not perform reverse DNS")

    monkeypatch.setattr(socket, "getfqdn", fail_reverse_dns)
    server = RuntimeHTTPServer.__new__(RuntimeHTTPServer)
    ThreadingHTTPServer.__init__(
        server,
        ("127.0.0.1", 0),
        RuntimeRequestHandler,
        bind_and_activate=False,
    )
    try:
        server.server_bind()
        host, port = server.server_address

        assert host == "127.0.0.1"
        assert port > 0
        assert server.server_name == host
        assert server.server_port == port
        assert lookups == []
    finally:
        server.server_close()
