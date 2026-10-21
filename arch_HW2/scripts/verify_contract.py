#!/usr/bin/env python3
"""Check OpenAPI and live responses."""
from pathlib import Path
from urllib.parse import urlsplit
from decimal import Decimal
import yaml
from jsonschema import RefResolver, ValidationError, validators
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate
from demo import Demonstration

ROOT = Path(__file__).resolve().parents[1]


def decimal_schema(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: decimal_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimal_schema(item) for item in value]
    return value


spec = decimal_schema(yaml.safe_load((ROOT / 'src/main/resources/openapi/marketplace.yaml').read_text()))
validate(spec)
print('PASS: OpenAPI specification is valid')


def decimal_multiple_of(validator, divisor, instance, schema):
    if validator.is_type(instance, 'number') and Decimal(str(instance)) % Decimal(str(divisor)) != 0:
        yield ValidationError(f'{instance} must be a multiple of {divisor}')


# Check money with Decimal.
ContractValidator = validators.extend(OAS30Validator, {'multipleOf': decimal_multiple_of})


def check_response(method, url, status, body):
    path = urlsplit(url).path
    matched = None
    for template, path_item in spec['paths'].items():
        parts, actual = template.strip('/').split('/'), path.strip('/').split('/')
        if len(parts) == len(actual) and all(a == b or a.startswith('{') for a, b in zip(parts, actual)):
            if method.lower() in path_item:
                matched = path_item[method.lower()]
                break
    assert matched is not None, f'Undocumented operation: {method} {path}'
    response = matched['responses'].get(str(status))
    assert response is not None, f'Undocumented response: {method} {path}: {status}'
    if '$ref' in response:
        response = spec['components']['responses'][response['$ref'].split('/')[-1]]
    if status == 204:
        assert body is None
    else:
        schema = response['content']['application/json']['schema']
        ContractValidator(schema, resolver=RefResolver.from_schema(spec), format_checker=OAS30Validator.FORMAT_CHECKER).validate(body)


if __name__ == '__main__':
    Demonstration(validate_response=check_response).run()
    print('PASS: all live responses conform to the source OpenAPI contract')
