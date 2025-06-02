import redis
import requests
REDIS_HOST = '192.168.0.121'
BASE_URL = 'https://cjremmett.com/logging'


def get_redis_cursor(host='localhost', port=6379):
    return redis.Redis(host, port, db=0, decode_responses=True)


def get_secrets_dict():
    r = get_redis_cursor(host=REDIS_HOST)
    secrets_list = r.json().get('secrets', '$')
    return secrets_list[0]


def get_logging_microservice_token() -> str:
    return get_secrets_dict()['secrets']['logging_microservice']['api_token']


def get_finance_token() -> str:
    return get_secrets_dict()['secrets']['finance_tools']['api_token']


def append_to_log(level: str, message: str) -> None:
    json = {'table': 'cjremmett_logs', 'category': 'AI', 'level': level, 'message': message}
    headers = {'token': get_logging_microservice_token()}
    requests.post(BASE_URL + '/append-to-log', json=json, headers=headers)


def log_resource_access(url: str, ip: str) -> None:
    json = {'resource': url, 'ip_address': ip}
    headers = {'token': get_logging_microservice_token()}
    requests.post(BASE_URL + '/log-resource-access', json=json, headers=headers)