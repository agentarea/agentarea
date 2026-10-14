"""Outbound TLS trust: public roots by default, plus the CAs a deployment adds."""

import datetime
import ipaddress
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certifi
import httpx
import httpx2
import pytest
from agentarea_common.config import get_settings
from agentarea_common.utils.outbound_tls import (
    OutboundTrustError,
    install_outbound_trust,
    outbound_ssl_context,
)
from agentarea_common.utils.url_safety import OutboundPolicy, PinnedSender, SafeOutboundTransport
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ENV = "AGENTAREA_HTTP_EXTRA_CA_CERTS"


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _issue(tmp: Path) -> tuple[Path, Path, Path]:
    """A private CA and a localhost certificate it signed: (ca.pem, cert.pem, key.pem)."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("AgentArea Test Root CA"))
        .issuer_name(_name("AgentArea Test Root CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("localhost"))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem = tmp / "ca.pem"
    cert_pem = tmp / "cert.pem"
    key_pem = tmp / "key.pem"
    ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_pem.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_pem, cert_pem, key_pem


class _Hello(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def private_ca_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """An HTTPS server on localhost whose certificate a private CA issued: (url, ca.pem)."""
    ca_pem, cert_pem, key_pem = _issue(tmp_path)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_pem, key_pem)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_address[1]}/spec.json", ca_pem
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _fresh_trust(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(ENV, raising=False)
    get_settings.cache_clear()
    outbound_ssl_context.cache_clear()
    yield
    get_settings.cache_clear()
    outbound_ssl_context.cache_clear()


def _configure(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ENV, value)
    get_settings.cache_clear()
    outbound_ssl_context.cache_clear()


async def _loopback(host: str, port: int) -> list[str]:
    return ["127.0.0.1"]


def _pinned_client() -> httpx.AsyncClient:
    """The client every member-supplied URL goes through, pointed at loopback."""
    transport = SafeOutboundTransport(OutboundPolicy(allow_private=True), resolve=_loopback)
    return httpx.AsyncClient(transport=transport)


class _MCPTransport(httpx2.AsyncBaseTransport):
    """The httpx2 side of the pinned sender, as the MCP SDK's client uses it."""

    def __init__(self) -> None:
        self._sender = PinnedSender(
            httpx2,
            OutboundPolicy(allow_private=True),
            error=httpx2.RequestError,
            resolve=_loopback,
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await self._sender.send(request)

    async def aclose(self) -> None:
        await self._sender.aclose()


async def test_a_host_signed_by_a_private_ca_is_refused_by_default(private_ca_server):
    url, _ca = private_ca_server

    async with _pinned_client() as client:
        with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
            await client.get(url)


async def test_the_same_host_is_reached_once_the_deployment_trusts_its_ca(
    private_ca_server, monkeypatch
):
    url, ca = private_ca_server
    _configure(monkeypatch, str(ca))

    async with _pinned_client() as client:
        response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_the_mcp_client_trusts_the_same_ca(private_ca_server, monkeypatch):
    url, ca = private_ca_server

    async with httpx2.AsyncClient(transport=_MCPTransport()) as client:
        with pytest.raises(httpx2.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
            await client.get(url)

    _configure(monkeypatch, str(ca))
    async with httpx2.AsyncClient(transport=_MCPTransport()) as client:
        response = await client.get(url)

    assert response.status_code == 200


def test_a_configured_ca_is_added_to_the_public_roots_not_put_in_their_place(
    tmp_path, monkeypatch
):
    ca, _cert, _key = _issue(tmp_path)
    public_roots = len(outbound_ssl_context().get_ca_certs())
    assert public_roots >= len(ssl.create_default_context(cafile=certifi.where()).get_ca_certs())

    _configure(monkeypatch, str(ca))
    subjects = [cert["subject"] for cert in outbound_ssl_context().get_ca_certs()]

    assert len(subjects) == public_roots + 1
    assert ((("commonName", "AgentArea Test Root CA"),),) in subjects


def test_a_missing_bundle_stops_startup(tmp_path, monkeypatch):
    _configure(monkeypatch, str(tmp_path / "absent.pem"))

    with pytest.raises(OutboundTrustError, match=ENV):
        install_outbound_trust()


def test_a_file_without_certificates_stops_startup(tmp_path, monkeypatch):
    junk = tmp_path / "junk.pem"
    junk.write_text("not a certificate\n")
    _configure(monkeypatch, str(junk))

    with pytest.raises(OutboundTrustError, match=ENV):
        install_outbound_trust()
