# Notyza para Python

O cliente oficial da API do [Notyza](https://notyza.com.br): NFS-e, NF-e, NFC-e e MDF-e para empresas do Simples Nacional, e a
conferência dos webhooks assinados. Só a biblioteca padrão, Python 3.10+.

## Instalar

```bash
pip install notyza
```

[![PyPI](https://img.shields.io/pypi/v/notyza)](https://pypi.org/project/notyza/)

## Emitir

```python
import os
from notyza import Notyza, NotyzaError

notyza = Notyza(api_key=os.environ["NOTYZA_API_KEY"])

nota = notyza.notas.issue({
    "id": "pedido-1001",  # o id do seu pedido: o mesmo id nunca emite duas vezes
    "serviceCode": "040101",
    "description": "Consulta médica",
    "valueCents": 25000,
})
if nota["httpStatus"] == 422:
    for error in nota["errors"]:
        print(error["explanation"], error["fix"])
```

Também: `notyza.nfe`, `notyza.nfce`, `notyza.mdfe`, `notyza.issuers`, `notyza.webhooks`, `notyza.notas.diagnose` e
`notyza.lookups`. Qualquer outra rota: `notyza.request(method, path, body)`.

## Webhooks

```python
from notyza import verify_webhook

# O corpo cru, exatamente como chegou.
if not verify_webhook(request.headers["Notyza-Signature"], request.get_data(), os.environ["NOTYZA_WEBHOOK_SECRET"]):
    abort(401)
```

## Respostas

- **200**: emitida. **202**: ainda com o governo; pergunte de novo com o mesmo `id` (nunca emite duas vezes) ou espere o webhook `nota.issued`.
- **422**: recusada. Vem como resposta, não como erro: mostre `errors[].explanation` e `errors[].fix` (a causa e como corrigir, em português).
- Qualquer outro 4xx/5xx vira exceção com o `code` estável da API (`plan_company_limit`, `payment_required`…) e a frase para mostrar.
- Chave `ek_test_…`: produção restrita do governo, sem valor fiscal. `ek_live_…`: notas de verdade.

Documentação completa: https://notyza.com.br/docs (também em `/llms-full.txt` para assistentes de IA). OpenAPI: https://api.notyza.com.br/v1/openapi.json.

## Licença

MIT.
