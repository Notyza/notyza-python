import hashlib
import hmac
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from notyza import Notyza, NotyzaError, verify_webhook  # noqa: E402


def fake(answers):
    """A transport that answers by "METHOD /path" and records the calls."""
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "body": json.loads(body) if body and headers.get("content-type") == "application/json" else body})
        path = url.split("api.notyza.test", 1)[1].split("?", 1)[0]
        status, payload = answers.get(f"{method} {path}", (404, {"error": "Rota não encontrada.", "code": "not_found"}))
        return status, json.dumps(payload).encode()

    return transport, calls


class ClientTest(unittest.TestCase):
    def test_refuses_a_key_that_is_not_a_notyza_key(self):
        with self.assertRaises(ValueError):
            Notyza(api_key="sk_x")
        self.assertEqual(Notyza(api_key="ek_live_x").mode, "live")

    def test_issues_and_answers_200_and_422_alike(self):
        transport, calls = fake({"POST /v1/notas": (200, {"id": "pedido-1", "status": "issued"}), "POST /v1/nfe": (422, {"status": "rejected"})})
        notyza = Notyza(api_key="ek_test_abc", base_url="https://api.notyza.test/", transport=transport)
        nota = notyza.notas.issue({"id": "pedido-1", "valueCents": 25000})
        self.assertEqual(nota["status"], "issued")
        self.assertEqual(nota["httpStatus"], 200)
        self.assertEqual(calls[0]["url"], "https://api.notyza.test/v1/notas")
        self.assertEqual(calls[0]["headers"]["authorization"], "Bearer ek_test_abc")
        self.assertEqual(calls[0]["body"], {"id": "pedido-1", "valueCents": 25000})
        self.assertEqual(notyza.nfe.issue({"id": "p2"})["httpStatus"], 422)

    def test_raises_with_the_api_code_and_sentence(self):
        transport, _ = fake({"POST /v1/issuers": (403, {"error": "O plano Grátis permite 1 empresa.", "code": "plan_company_limit"})})
        notyza = Notyza(api_key="ek_test_abc", base_url="https://api.notyza.test", transport=transport)
        with self.assertRaises(NotyzaError) as caught:
            notyza.issuers.create({"cnpj": "11222333000181"})
        self.assertEqual((caught.exception.status, caught.exception.code, caught.exception.message), (403, "plan_company_limit", "O plano Grátis permite 1 empresa."))

    def test_query_strings_ids_and_the_void(self):
        transport, calls = fake({"GET /v1/notas": (200, {"notas": []}), "POST /v1/nfce/void": (200, {"status": "voided"})})
        notyza = Notyza(api_key="ek_test_abc", base_url="https://api.notyza.test", transport=transport)
        notyza.notas.list(model="mdfe", status="issued", limit=10)
        self.assertEqual(calls[0]["url"], "https://api.notyza.test/v1/notas?model=mdfe&status=issued&limit=10")
        notyza.nfce.void_numbers(10, 12, "Falha do sistema: números pulados")
        self.assertEqual(calls[1]["body"], {"from": 10, "to": 12, "reason": "Falha do sistema: números pulados"})


class WebhookTest(unittest.TestCase):
    secret = "whsec_teste"
    body = '{"type":"nota.issued","data":{"id":"pedido-1"}}'

    def sign(self, t, key=None):
        return f"t={t},v1=" + hmac.new((key or self.secret).encode(), f"{t}.{self.body}".encode(), hashlib.sha256).hexdigest()

    def test_accepts_the_right_signature_also_during_a_rotation(self):
        self.assertTrue(verify_webhook(self.sign(1000), self.body, self.secret, now=1010))
        rotated = f"{self.sign(1000, 'whsec_novo')},v1={self.sign(1000).split('v1=')[1]}"
        self.assertTrue(verify_webhook(rotated, self.body.encode(), self.secret, now=1010))

    def test_refuses_wrong_secret_changed_body_and_old_signature(self):
        self.assertFalse(verify_webhook(self.sign(1000, "outro"), self.body, self.secret, now=1010))
        self.assertFalse(verify_webhook(self.sign(1000), self.body + " ", self.secret, now=1010))
        self.assertFalse(verify_webhook(self.sign(1000), self.body, self.secret, now=1301))
        self.assertFalse(verify_webhook("lixo", self.body, self.secret))


if __name__ == "__main__":
    unittest.main()
