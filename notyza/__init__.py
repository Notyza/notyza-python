"""The official Python client of the Notyza API: NFS-e, NF-e, NFC-e and MDF-e, and signed webhooks.

Thin by design: each method is one route of /v1 (docs: /llms-full.txt, OpenAPI: /v1/openapi.json); the errors carry the
API's own ``code`` and Portuguese message; ``verify_webhook`` checks the ``Notyza-Signature`` header. Standard library only.

    from notyza import Notyza
    notyza = Notyza(api_key=os.environ["NOTYZA_API_KEY"])
    nota = notyza.notas.issue({"id": "pedido-1001", "serviceCode": "040101", "description": "Consulta", "valueCents": 25000})
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

__all__ = ["Notyza", "NotyzaError", "verify_webhook"]
__version__ = "0.1.0"

Json = Dict[str, Any]
# (method, url, headers, body bytes or None, timeout) -> (status, body bytes)
Transport = Callable[[str, str, Dict[str, str], Optional[bytes], float], "tuple[int, bytes]"]


class NotyzaError(Exception):
    """An answer the API refused (4xx/5xx): ``code`` is stable, ``message`` is the sentence to show."""

    def __init__(self, status: int, code: str, message: str, body: Json):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.body = body


def _urllib_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout: float) -> "tuple[int, bytes]":
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _query(params: Dict[str, Any]) -> str:
    clean = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in params.items() if value not in (None, "")}
    return f"?{urllib.parse.urlencode(clean)}" if clean else ""


def _id(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


class _Resource:
    def __init__(self, client: "Notyza", base: str):
        self._client = client
        self._base = base

    def _doc(self, method: str, path: str, body: Optional[Json] = None) -> Json:
        # A document's answer: 200 issued, 202 with the government (ask again with the same id), 422 refused.
        return self._client.request(method, path, body, accept=(422,))


class _Notas(_Resource):
    def issue(self, nota: Json) -> Json:
        """The same ``id`` never issues twice: asking again answers with the nota already there."""
        return self._doc("POST", "/v1/notas", nota)

    def get(self, id: str, issuer: Optional[str] = None, xml: bool = False) -> Json:
        return self._client.request("GET", f"/v1/notas/{_id(id)}{_query({'issuer': issuer, 'xml': 1 if xml else None})}")

    def list(self, **filters: Any) -> Json:
        return self._client.request("GET", f"/v1/notas{_query(filters)}")

    def cancel(self, id: str, **body: Any) -> Json:
        return self._doc("POST", f"/v1/notas/{_id(id)}/cancel", body)

    def substitute(self, id: str, body: Json) -> Json:
        return self._doc("POST", f"/v1/notas/{_id(id)}/substitute", body)

    def pdf(self, id: str, issuer: Optional[str] = None) -> bytes:
        return self._client.raw("GET", f"/v1/notas/{_id(id)}/pdf{_query({'issuer': issuer})}")

    def diagnose(self, **body: Any) -> Json:
        """Why the government refused (``nota`` of the account, or ``code``): the cause, the fix and the field."""
        return self._client.request("POST", "/v1/diagnose", body)


class _Goods(_Resource):
    """NF-e (/v1/nfe) or NFC-e (/v1/nfce)."""

    def issue(self, document: Json) -> Json:
        return self._doc("POST", self._base, document)

    def get(self, id: str, issuer: Optional[str] = None) -> Json:
        return self._client.request("GET", f"{self._base}/{_id(id)}{_query({'issuer': issuer})}")

    def cancel(self, id: str, **body: Any) -> Json:
        return self._doc("POST", f"{self._base}/{_id(id)}/cancel", body)

    def void_numbers(self, from_number: int, to_number: int, reason: str, issuer: Optional[str] = None) -> Json:
        """Inutilização of a range of the series: 200 voided, 422 refused by SEFAZ."""
        return self._doc("POST", f"{self._base}/void", {"from": from_number, "to": to_number, "reason": reason, **({"issuer": issuer} if issuer else {})})

    def pdf(self, id: str, issuer: Optional[str] = None) -> bytes:
        return self._client.raw("GET", f"{self._base}/{_id(id)}/pdf{_query({'issuer': issuer})}")


class _Nfe(_Goods):
    def correct(self, id: str, text: str, issuer: Optional[str] = None) -> Json:
        return self._client.request("POST", f"/v1/nfe/{_id(id)}/correction", {"text": text, **({"issuer": issuer} if issuer else {})})

    def return_sale(self, id: str, body: Json) -> Json:
        return self._doc("POST", f"/v1/nfe/{_id(id)}/return", body)


class _Mdfe(_Resource):
    def issue(self, mdfe: Json) -> Json:
        return self._doc("POST", "/v1/mdfe", mdfe)

    def get(self, id: str, issuer: Optional[str] = None) -> Json:
        return self._client.request("GET", f"/v1/mdfe/{_id(id)}{_query({'issuer': issuer})}")

    def close(self, id: str, **body: Any) -> Json:
        return self._client.request("POST", f"/v1/mdfe/{_id(id)}/close", body)

    def add_driver(self, id: str, driver: Any, issuer: Optional[str] = None) -> Json:
        return self._client.request("POST", f"/v1/mdfe/{_id(id)}/drivers", {"driver": driver, **({"issuer": issuer} if issuer else {})})

    def cancel(self, id: str, **body: Any) -> Json:
        return self._doc("POST", f"/v1/mdfe/{_id(id)}/cancel", body)

    def open(self, issuer: Optional[str] = None) -> Json:
        return self._client.request("GET", f"/v1/mdfe/open{_query({'issuer': issuer})}")


class _Cte(_Resource):
    def issue(self, cte: Json) -> Json:
        return self._doc("POST", "/v1/cte", cte)

    def get(self, id: str, issuer: Optional[str] = None) -> Json:
        return self._client.request("GET", f"/v1/cte/{_id(id)}{_query({'issuer': issuer})}")

    def correct(self, id: str, corrections: List[Json], issuer: Optional[str] = None) -> Json:
        """A carta de correção: [{"group", "field", "value", "item"?}]; never values, parties or dates."""
        return self._client.request("POST", f"/v1/cte/{_id(id)}/correction", {"corrections": corrections, **({"issuer": issuer} if issuer else {})})

    def cancel(self, id: str, **body: Any) -> Json:
        return self._doc("POST", f"/v1/cte/{_id(id)}/cancel", body)

    def complement(self, id: str, body: Json) -> Json:
        """The value that was missing of an authorized freight (the same parties)."""
        return self._doc("POST", f"/v1/cte/{_id(id)}/complement", body)

    def substitute(self, id: str, body: Json) -> Json:
        """The same freight with what was wrong fixed; SEFAZ accepts it after the tomador's disagreement."""
        return self._doc("POST", f"/v1/cte/{_id(id)}/substitute", body)

    def disagree(self, key: str, reason: str, issuer: Optional[str] = None) -> Json:
        """The tomador's side: the service of a CT-e it paid for was not as agreed."""
        return self._client.request("POST", "/v1/cte/disagreement", {"key": key, "reason": reason, **({"issuer": issuer} if issuer else {})})


class _Issuers(_Resource):
    def create(self, body: Json) -> Json:
        return self._client.request("POST", "/v1/issuers", body)

    def list(self) -> Json:
        return self._client.request("GET", "/v1/issuers")

    def get(self, id: str) -> Json:
        return self._client.request("GET", f"/v1/issuers/{_id(id)}")

    def update(self, id: str, body: Json) -> Json:
        return self._client.request("PATCH", f"/v1/issuers/{_id(id)}", body)

    def checklist(self, id: str) -> Json:
        return self._client.request("GET", f"/v1/issuers/{_id(id)}/checklist")

    def certificate_link(self, id: str) -> Json:
        """A one-use panel link (30 minutes) where the person sends the .pfx and its password."""
        return self._client.request("POST", f"/v1/issuers/{_id(id)}/certificate-link")

    def upload_certificate(self, id: str, pfx: bytes, password: str) -> Json:
        boundary = f"notyza{int(time.time() * 1000)}"
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="password"\r\n\r\n{password}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="certificate"; filename="certificado.pfx"\r\nContent-Type: application/x-pkcs12\r\n\r\n'.encode() + pfx + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self._client.request("POST", f"/v1/issuers/{_id(id)}/certificate", raw=b"".join(parts), content_type=f"multipart/form-data; boundary={boundary}")

    def enable_production(self, id: str) -> Json:
        return self._client.request("POST", f"/v1/issuers/{_id(id)}/production")


class _Webhooks(_Resource):
    def create(self, url: str, events: Optional[Iterable[str]] = None) -> Json:
        return self._client.request("POST", "/v1/webhooks", {"url": url, **({"events": list(events)} if events else {})})

    def list(self) -> Json:
        return self._client.request("GET", "/v1/webhooks")

    def remove(self, id: str) -> Json:
        return self._client.request("DELETE", f"/v1/webhooks/{_id(id)}")


class _Lookups(_Resource):
    def city(self, city_code: str) -> Json:
        return self._client.request("GET", f"/v1/public/cities/{_id(city_code)}")

    def service_codes(self, q: str, limit: int = 20) -> Json:
        return self._client.request("GET", f"/v1/public/service-codes{_query({'q': q, 'limit': limit})}")

    def ibs_cbs(self, service_code: str) -> Json:
        return self._client.request("GET", f"/v1/public/service-codes/{_id(service_code)}/ibs-cbs")

    def access_key(self, key: str) -> Json:
        return self._client.request("GET", f"/v1/public/access-keys/{_id(key.replace(' ', ''))}")

    def tax_id(self, value: str) -> Json:
        return self._client.request("POST", "/v1/public/tax-id", {"value": value})


class Notyza:
    def __init__(self, api_key: str, base_url: str = "https://api.notyza.com.br", timeout: float = 60.0, transport: Optional[Transport] = None):
        if not str(api_key or "").startswith(("ek_test_", "ek_live_")):
            raise ValueError("Notyza: api_key precisa ser uma chave ek_test_… ou ek_live_….")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _urllib_transport
        self.notas = _Notas(self, "/v1/notas")
        self.nfe = _Nfe(self, "/v1/nfe")
        self.nfce = _Goods(self, "/v1/nfce")
        self.mdfe = _Mdfe(self, "/v1/mdfe")
        self.cte = _Cte(self, "/v1/cte")
        self.issuers = _Issuers(self, "/v1/issuers")
        self.webhooks = _Webhooks(self, "/v1/webhooks")
        self.lookups = _Lookups(self, "/v1/public")

    @property
    def mode(self) -> str:
        """``test`` (no fiscal value) or ``live``."""
        return "live" if self.api_key.startswith("ek_live_") else "test"

    def _send(self, method: str, path: str, body: Optional[bytes], content_type: Optional[str]) -> "tuple[int, bytes]":
        headers = {"authorization": f"Bearer {self.api_key}", "accept": "application/json", "user-agent": f"notyza-python/{__version__}"}
        if content_type:
            headers["content-type"] = content_type
        return self._transport(method, f"{self.base_url}{path}", headers, body, self.timeout)

    def request(self, method: str, path: str, body: Optional[Json] = None, accept: Iterable[int] = (), raw: Optional[bytes] = None, content_type: Optional[str] = None) -> Json:
        """Any route of /v1. Answers the JSON plus ``httpStatus``; raises NotyzaError on 4xx/5xx except ``accept``."""
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        status, data = self._send(method, path, payload, content_type or ("application/json" if body is not None else None))
        try:
            parsed: Json = json.loads(data.decode() or "{}")
        except ValueError:
            parsed = {"error": data.decode(errors="replace")[:500]}
        if status >= 400 and status not in tuple(accept):
            raise NotyzaError(status, str(parsed.get("code", "http_error")), str(parsed.get("error", f"A API respondeu {status}.")), parsed)
        return {**parsed, "httpStatus": status}

    def raw(self, method: str, path: str) -> bytes:
        status, data = self._send(method, path, None, None)
        if status >= 400:
            parsed = json.loads(data.decode() or "{}") if data[:1] == b"{" else {}
            raise NotyzaError(status, str(parsed.get("code", "http_error")), str(parsed.get("error", f"A API respondeu {status}.")), parsed)
        return data


def verify_webhook(signature_header: str, raw_body: "bytes | str", secret: str, tolerance_seconds: int = 300, now: Optional[int] = None) -> bool:
    """Checks ``Notyza-Signature`` (``t=<unix>,v1=<hex>[,v1=<hex>]``): HMAC-SHA256 of "<t>.<raw body>" with the secret.

    Refuses signatures older than ``tolerance_seconds`` (replays). Pass the raw body exactly as received.
    """
    parts = [part.strip() for part in signature_header.split(",")]
    try:
        timestamp = int(next(part[2:] for part in parts if part.startswith("t=")))
    except (StopIteration, ValueError):
        return False
    if abs((now if now is not None else int(time.time())) - timestamp) > tolerance_seconds:
        return False
    body = raw_body.decode() if isinstance(raw_body, bytes) else raw_body
    expected = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(part[3:], expected) for part in parts if part.startswith("v1="))
