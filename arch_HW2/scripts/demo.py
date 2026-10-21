#!/usr/bin/env python3
"""Run HTTP → PostgreSQL checks with SELECT output."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]


def settings():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"\'')
    values.update(os.environ)
    return values


class Demonstration:
    def __init__(self, validate_response=None, verify_db=True):
        self.config = settings()
        self.base = self.config.get('API_URL', 'http://localhost:' + self.config.get('HOST_PORT', '8081')).rstrip('/')
        self.validate_response = validate_response
        self.verify_db = verify_db
        self.run_id = uuid4().hex[:10]
        self.traffic = []

    def call(self, method, path, body=None, token=None, expected=200, error=None):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as exception:
            response = exception
        with response:
            status, response_headers = response.status, response.headers
            payload = response.read()
        result = json.loads(payload, parse_float=Decimal) if payload else None
        assert status == expected, f'{method} {path}: expected {expected}, got {status}: {result}'
        request_id = response_headers.get('X-Request-Id')
        UUID(request_id)
        if result is not None:
            assert response_headers.get_content_type() == 'application/json'
        if error:
            assert result['error_code'] == error, result
        if self.validate_response:
            self.validate_response(method, path, status, result)
        print(f'{method:6} {path} → {status}' + (f' {error}' if error else ''))
        self.traffic.append({'method': method, 'path': path, 'status': status, 'request_id': request_id})
        return result

    def sql(self, statement, show=False):
        if not self.verify_db:
            return None
        command = ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'marketplace', '-d', 'marketplace', '-v', 'ON_ERROR_STOP=1']
        if not show:
            command.append('-tA')
        result = subprocess.run(command, input=statement + '\n', text=True, capture_output=True, cwd=ROOT, check=True)
        if show:
            print('\nSQL> ' + statement)
            print(result.stdout.rstrip())
        return result.stdout.strip()

    def assert_sql(self, statement, expected):
        actual = self.sql(statement)
        if self.verify_db:
            assert actual == str(expected), f'{statement}: expected {expected}, got {actual}'

    def login(self, email, password):
        return self.call('POST', '/auth/login', {'email': email, 'password': password})

    def register(self, label, role):
        email = f'{label}-{self.run_id}@example.test'
        password = 'Demo-password-123!'
        user = self.call('POST', '/auth/register', {'email': email, 'password': password, 'role': role}, expected=201)
        tokens = self.login(email, password)
        return user, tokens

    def product_body(self, name, price, stock=10, category=None):
        return {'name': name, 'description': None, 'price': price, 'stock': stock, 'category': category or 'demo_' + self.run_id, 'status': 'ACTIVE'}

    @staticmethod
    def items(product_id, quantity):
        UUID(product_id)
        return {'items': [{'product_id': product_id, 'quantity': quantity}]}

    def run(self):
        print('E2E run:', self.run_id, '| API:', self.base)
        print('\n1. Health, registration and JWT')
        self.call('GET', '/health')
        seller_user, seller_tokens = self.register('seller', 'SELLER')
        buyer_user, buyer_tokens = self.register('buyer', 'USER')
        other_user, other_tokens = self.register('other', 'USER')
        seller, buyer, other = seller_tokens['access_token'], buyer_tokens['access_token'], other_tokens['access_token']
        admin = self.login(self.config.get('ADMIN_EMAIL', 'admin@example.test'), self.config.get('ADMIN_PASSWORD', 'Admin-demo-123!'))['access_token']
        self.call('GET', '/products', expected=401, error='TOKEN_INVALID')
        self.call('GET', '/products', token=buyer_tokens['refresh_token'], expected=401, error='TOKEN_INVALID')
        self.call('POST', '/auth/refresh', {'refresh_token': buyer_tokens['refresh_token']})
        self.call('POST', '/auth/refresh', {'refresh_token': buyer_tokens['refresh_token']}, expected=401, error='REFRESH_TOKEN_INVALID')

        print('\n2. Product CRUD and input validation')
        body = self.product_body('Demo book ' + self.run_id, 100)
        product = self.call('POST', '/products', body, seller, 201)
        product_id = str(UUID(product['id']))
        self.call('GET', '/products/' + product_id, token=buyer)
        page = self.call('GET', '/products?category=demo_' + self.run_id + '&status=ACTIVE&page=0&size=1', token=buyer)
        assert page['totalElements'] == 1 and page['size'] == 1 and page['page'] == 0
        self.call('POST', '/products', body, buyer, 403, 'ACCESS_DENIED')
        self.call('POST', '/products', {**body, 'price': 0}, seller, 400, 'VALIDATION_ERROR')
        self.call('GET', '/products?size=0', token=buyer, expected=400, error='VALIDATION_ERROR')
        body['price'] = 120
        self.call('PUT', '/products/' + product_id, body, seller)

        print('\n3. Promo, order, reservation and SQL evidence')
        code = 'DEMO' + self.run_id.upper()
        now = datetime.now(timezone.utc)
        promo = self.call('POST', '/promo-codes', {'code': code, 'discount_type': 'PERCENTAGE', 'discount_value': 10, 'min_order_amount': 200, 'max_uses': 1, 'valid_from': (now - timedelta(hours=1)).isoformat(), 'valid_until': (now + timedelta(days=1)).isoformat(), 'active': True}, seller, 201)
        promo_id = str(UUID(promo['id']))
        order = self.call('POST', '/orders', {**self.items(product_id, 3), 'promo_code': code}, buyer, 201)
        order_id = str(UUID(order['id']))
        assert order['total_amount'] == Decimal('324.00') and order['discount_amount'] == Decimal('36.00')
        self.assert_sql(f"SELECT stock FROM products WHERE id='{product_id}';", 7)
        self.assert_sql(f"SELECT current_uses FROM promo_codes WHERE id='{promo_id}';", 1)
        self.sql(f"SELECT id,name,price,stock,status,seller_id FROM products WHERE id='{product_id}';", show=True)
        self.sql(f"SELECT id,user_id,status,total_amount,discount_amount,promo_code_id FROM orders WHERE id='{order_id}';", show=True)
        self.sql(f"SELECT product_id,quantity,price_at_order FROM order_items WHERE order_id='{order_id}';", show=True)
        self.sql(f"SELECT code,current_uses,max_uses FROM promo_codes WHERE id='{promo_id}';", show=True)
        self.sql(f"SELECT user_id,operation_type,created_at FROM user_operations WHERE user_id='{UUID(buyer_user['id'])}' ORDER BY created_at;", show=True)

        print('\n4. Ownership, roles, stock errors and rate limit')
        self.call('GET', '/orders/' + order_id, token=other, expected=403, error='ORDER_OWNERSHIP_VIOLATION')
        self.call('POST', '/orders', self.items(product_id, 1), seller, 403, 'ACCESS_DENIED')
        if int(self.config.get('ORDER_RATE_LIMIT_MINUTES', '1')) > 0:
            self.call('POST', '/orders', self.items(product_id, 1), buyer, 429, 'ORDER_LIMIT_EXCEEDED')
        self.call('POST', '/orders', self.items(product_id, 999), other, 409, 'INSUFFICIENT_STOCK')
        self.assert_sql(f"SELECT stock FROM products WHERE id='{product_id}';", 7)
        self.call('POST', '/orders', {**self.items(product_id, 1), 'promo_code': 'MISSING_' + self.run_id.upper()}, other, 422, 'PROMO_CODE_INVALID')
        self.assert_sql(f"SELECT stock FROM products WHERE id='{product_id}';", 7)

        print('\n5. Price snapshot, order update, promo removal and cancellation')
        self.call('PUT', '/products/' + product_id, {**body, 'price': 150, 'stock': 7}, seller)
        snapshot = self.call('GET', '/orders/' + order_id, token=buyer)
        assert snapshot['items'][0]['price_at_order'] == 120 and snapshot['total_amount'] == 324
        updated = self.call('PUT', '/orders/' + order_id, self.items(product_id, 1), buyer)
        assert updated['total_amount'] == 150 and updated['discount_amount'] == 0 and updated['promo_code_id'] is None
        self.assert_sql(f"SELECT stock FROM products WHERE id='{product_id}';", 9)
        self.assert_sql(f"SELECT current_uses FROM promo_codes WHERE id='{promo_id}';", 0)
        if int(self.config.get('ORDER_RATE_LIMIT_MINUTES', '1')) > 0:
            self.call('PUT', '/orders/' + order_id, self.items(product_id, 2), buyer, 429, 'ORDER_LIMIT_EXCEEDED')
        canceled = self.call('POST', '/orders/' + order_id + '/cancel', token=buyer)
        assert canceled['status'] == 'CANCELED'
        self.call('POST', '/orders/' + order_id + '/cancel', token=buyer, expected=409, error='INVALID_STATE_TRANSITION')
        self.assert_sql(f"SELECT stock FROM products WHERE id='{product_id}';", 10)
        self.sql(f"SELECT id,status,total_amount,discount_amount,promo_code_id FROM orders WHERE id='{order_id}';", show=True)
        self.sql(f"SELECT id,stock FROM products WHERE id='{product_id}';", show=True)

        print('\n6. Soft delete preserves the row')
        self.call('DELETE', '/products/' + product_id, token=seller, expected=204)
        archived = self.call('GET', '/products/' + product_id, token=buyer)
        assert archived['status'] == 'ARCHIVED'
        self.assert_sql(f"SELECT status FROM products WHERE id='{product_id}';", 'ARCHIVED')
        self.sql(f"SELECT id,name,status,stock FROM products WHERE id='{product_id}';", show=True)
        self.call('POST', '/orders', self.items(product_id, 1), other, 409, 'PRODUCT_INACTIVE')
        self.call('GET', '/products/' + str(uuid4()), token=buyer, expected=404, error='PRODUCT_NOT_FOUND')
        self.call('GET', '/orders/' + str(uuid4()), token=buyer, expected=404, error='ORDER_NOT_FOUND')

        print('\n7. State machine through ADMIN endpoint')
        second_product = self.call('POST', '/products', self.product_body('State machine ' + self.run_id, 10, 5), seller, 201)
        paid = self.call('POST', '/orders', self.items(second_product['id'], 1), other, 201)
        paid_id = str(UUID(paid['id']))
        self.call('PATCH', '/orders/' + paid_id + '/status', {'status': 'COMPLETED'}, admin, 409, 'INVALID_STATE_TRANSITION')
        for state in ('PAYMENT_PENDING', 'PAID', 'SHIPPED', 'COMPLETED'):
            assert self.call('PATCH', '/orders/' + paid_id + '/status', {'status': state}, admin)['status'] == state
        self.call('POST', '/orders/' + paid_id + '/cancel', token=other, expected=409, error='INVALID_STATE_TRANSITION')
        self.sql(f"SELECT id,status,total_amount FROM orders WHERE id='{paid_id}';", show=True)

        summary = {'run_id': self.run_id, 'requests': len(self.traffic), 'sql_verified': self.verify_db, 'product_id': product_id, 'order_id': order_id, 'promo_id': promo_id, 'traffic': self.traffic}
        print(f'\nPASS: {len(self.traffic)} real HTTP requests' + (' and PostgreSQL SELECT assertions' if self.verify_db else '') + '.')
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-db', action='store_true', help='HTTP only; the default also demonstrates SELECT through Docker Compose')
    parser.add_argument('--evidence', type=Path, help='Save sanitized request IDs/statuses, without credentials or JWTs')
    args = parser.parse_args()
    summary = Demonstration(verify_db=not args.skip_db).run()
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
