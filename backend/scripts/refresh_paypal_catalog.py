"""Opt-in download of public API metadata only; never invokes a PayPal operation."""
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen

REPOSITORY = 'https://api.github.com/repos/paypal/paypal-rest-api-specifications'
SPECS = ['invoicing_v2.json', 'reporting_transactions_v1.json', 'customer_disputes_v1.json',
         'checkout_orders_v2.json', 'payments_payment_v2.json', 'billing_subscriptions_v1.json']


def main():
    with urlopen(REPOSITORY+'/commits/main', timeout=30) as response:
        revision = json.load(response)['sha']
    operations = []
    for filename in SPECS:
        source = f'https://raw.githubusercontent.com/paypal/paypal-rest-api-specifications/{revision}/openapi/{filename}'
        with urlopen(source, timeout=30) as response:
            raw = response.read()
        spec = json.loads(raw)
        for path, methods in spec['paths'].items():
            for method, operation in methods.items():
                if method not in {'get','post','put','patch','delete','head','options'}:
                    continue
                operation_id = operation.get('operationId', method+'_'+path)
                name = 'catalog_paypal_'+re.sub('[^a-zA-Z0-9_]', '_', filename[:-5]+'_'+operation_id)
                operations.append({'id': name, 'service': 'paypal', 'capability': operation.get('summary', operation_id),
                    'description': f"PayPal {filename[:-5]}: {operation.get('summary', operation_id)}. {method.upper()} {path}",
                    'method': method.upper(), 'path': path, 'schema_ref': source+'#/paths/'+path.replace('~','~0').replace('/','~1')+'/'+method,
                    'source': source, 'source_sha256': hashlib.sha256(raw).hexdigest(), 'version': revision,
                    'executable': False})
    target = Path(__file__).resolve().parents[1]/'src/agent_backend/catalog/paypal-v1.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'version': 1, 'upstream_revision': revision,
        'note': 'Official operation metadata; not executable handlers or a complete imported schema. Demo schemas are separate.',
        'operations': operations}, indent=2)+'\n', encoding='utf-8')
    print(f'Saved {len(operations)} operations at revision {revision}')


if __name__ == '__main__':
    main()
