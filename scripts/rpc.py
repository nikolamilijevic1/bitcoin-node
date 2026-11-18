"""Small standard-library clients. Defaults to regtest; configurable via env."""
import base64
import http.client
import json
import os
import socket
import threading


class RPCError(RuntimeError):
    pass


_local = threading.local()


def _rpc_settings():
    host = os.environ.get('BITCOIN_RPC_HOST', 'bitcoin')
    port = int(os.environ.get('BITCOIN_RPC_PORT', '18443'))
    user = os.environ.get('BITCOIN_RPC_USER', 'regtest')
    password = os.environ.get('BITCOIN_RPC_PASSWORD', 'local-regtest-only')
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    return host, port, auth


def _request(payload, wallet=None):
    host, port, auth = _rpc_settings()
    path = '/wallet/' + wallet if wallet else '/'
    if not getattr(_local, 'connection', None):
        _local.connection = http.client.HTTPConnection(host, port, timeout=60)
    try:
        _local.connection.request('POST', path,
            body=json.dumps(payload),
            headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
        result = json.loads(_local.connection.getresponse().read())
    except Exception:
        _local.connection.close()
        _local.connection = None
        raise  # Never blindly retry a state-changing RPC after a transport error.
    return result


def rpc(method, params=None, wallet=None):
    result = _request({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or []}, wallet)
    if result.get('error'):
        raise RPCError(str(result['error']))
    return result['result']


def rpc_batch(calls, wallet=None, allow_errors=False):
    result = _request([{'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}
                       for i, (method, params) in enumerate(calls)], wallet)
    by_id = {item['id']: item for item in result}
    ordered = [by_id[i] for i in range(len(calls))]
    if allow_errors:
        return ordered
    for item in ordered:
        if item.get('error'):
            raise RPCError(str(item['error']))
    return [item['result'] for item in ordered]


def require_network(expected='regtest'):
    info = rpc('getblockchaininfo')
    if expected and info['chain'] != expected:
        raise RuntimeError(f"Refusing to run outside {expected} (found {info['chain']})")
    return info


def require_regtest():
    return require_network('regtest')


def electrum(method, params=None):
    host = os.environ.get('ELECTRS_HOST', 'electrs')
    port = int(os.environ.get('ELECTRS_PORT', '50001'))
    with socket.create_connection((host, port), timeout=15) as sock:
        sock.sendall((json.dumps({'id': 1, 'method': method, 'params': params or []}) + '\n').encode())
        with sock.makefile('r') as stream:
            result = json.loads(stream.readline())
    if result.get('error'):
        raise RPCError(str(result['error']))
    return result['result']
