"""Small standard-library clients. This lab deliberately refuses non-regtest chains."""
import base64
import json
import http.client
import socket
import threading


class RPCError(RuntimeError):
    pass


_local = threading.local()


def _request(payload, wallet=None):
    path = '/wallet/' + wallet if wallet else '/'
    if not getattr(_local, 'connection', None):
        _local.connection = http.client.HTTPConnection('bitcoin', 18443, timeout=60)
    try:
        _local.connection.request('POST', path,
            body=json.dumps(payload),
            headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' +
                     base64.b64encode(b'regtest:local-regtest-only').decode()})
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


def require_regtest():
    info = rpc('getblockchaininfo')
    if info['chain'] != 'regtest':
        raise RuntimeError('Refusing to run outside regtest')
    return info


def electrum(method, params=None):
    with socket.create_connection(('electrs', 50001), timeout=15) as sock:
        sock.sendall((json.dumps({'id': 1, 'method': method, 'params': params or []}) + '\n').encode())
        with sock.makefile('r') as stream:
            result = json.loads(stream.readline())
    if result.get('error'):
        raise RPCError(str(result['error']))
    return result['result']
