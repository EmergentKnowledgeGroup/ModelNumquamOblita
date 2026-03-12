from engine.runtime.server import _host_is_loopback


def test_host_is_loopback_accepts_standard_loopback_variants() -> None:
    assert _host_is_loopback("127.0.0.1") is True
    assert _host_is_loopback("::1") is True
    assert _host_is_loopback("::ffff:127.0.0.1") is True
    assert _host_is_loopback("localhost") is True


def test_host_is_loopback_rejects_non_loopback_and_invalid_hosts() -> None:
    assert _host_is_loopback("192.168.1.10") is False
    assert _host_is_loopback("example.com") is False
    assert _host_is_loopback("") is False
