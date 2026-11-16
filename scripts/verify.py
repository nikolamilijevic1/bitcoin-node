"""Integration checks against Core, electrs, explorer pagination, and monitoring."""
import hashlib
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from rpc import rpc, electrum, require_regtest


def get(path):
    with urllib.request.urlopen('http://web:8080/api/' + path, timeout=60) as response:
        return json.load(response)


def run():
    started = time.monotonic()
    s = json.loads(Path('/dataset/state.json').read_text())
    assert s['status'] == 'complete', 'Generator not complete'
    info = require_regtest()
    assert not rpc('getrawmempool'), 'Unexpected pending transactions'
    assert electrum('blockchain.headers.subscribe')['height'] == info['blocks'], 'Index behind'
    chain_transactions = rpc('getchaintxstats')['txcount']
    assert chain_transactions == s['target'] + info['blocks'] + 1, 'Unexpected chain transaction count'
    measurements = []
    for example in s['examples'][:12]:
        begin = time.monotonic()
        tx = get('tx/' + example['txid'])
        measurements.append(time.monotonic() - begin)
        core = rpc('getrawtransaction', [example['txid'], True])
        assert tx['status']['confirmed']
        assert tx['fee'] == 2000
        assert [(v['txid'], v['vout']) for v in tx['vin']] == [(v['txid'], v['vout']) for v in core['vin']]
        assert [v['value'] for v in tx['vout']] == [round(v['value'] * 100000000) for v in core['vout']]
        outspends = get('tx/' + example['txid'] + '/outspends')
        assert not outspends[0]['spent'], 'Recipient output should remain unspent'
        assert outspends[-1]['spent'], 'Continuing path should be spent later'
        child = get('tx/' + outspends[-1]['txid'])
        assert any(v['txid'] == example['txid'] and v['vout'] == len(tx['vout'])-1 for v in child['vin'])
    address = s['addresses'][0]
    summary = get('address/' + address)
    expected = (s['target'] + 4) // 5
    assert summary['chain_stats']['tx_count'] == expected
    assert summary['chain_stats']['funded_txo_sum'] - summary['chain_stats']['spent_txo_sum'] == expected * 10000
    # Walk every page, rather than checking only the first page of a busy address.
    script = rpc('validateaddress', [address])['scriptPubKey']
    script_hash = hashlib.sha256(bytes.fromhex(script)).digest()[::-1].hex()
    history = electrum('blockchain.scripthash.get_history', [script_hash])
    expected_ids = {item['tx_hash'] for item in history}
    seen = set()
    suffix = ''
    pages = 0
    while True:
        batch = get('address/' + address + '/txs/chain' + suffix)
        if not batch:
            break
        ids = {tx['txid'] for tx in batch}
        assert not seen.intersection(ids), 'Duplicate pagination results'
        seen.update(ids)
        suffix = '/' + batch[-1]['txid']
        pages += 1
        assert pages <= expected + 1, 'Pagination did not terminate'
    assert seen == expected_ids, 'Incomplete explorer history'
    # Remaining address types must also be queryable.
    for address in s['addresses'][1:4]:
        assert get('address/' + address)['chain_stats']['tx_count'] > 0
    with urllib.request.urlopen('http://prometheus:9090/api/v1/targets') as response:
        targets = json.load(response)['data']['activeTargets']
    assert all(t['health'] == 'up' for t in targets), 'Metrics target down'
    request = urllib.request.Request('http://web:8080/api/tx', data=b'invalid', method='POST')
    try:
        urllib.request.urlopen(request, timeout=5)
        raise AssertionError('Explorer unexpectedly allowed a write request')
    except urllib.error.HTTPError as error:
        assert error.code == 403, f'Expected read-only denial, received {error.code}'
    report = {'result': 'passed', 'generated_transactions': s['completed'], 'height': info['blocks'],
              'busy_address_transactions': len(seen), 'pages_verified': pages,
              'sample_transaction_mean_seconds': round(sum(measurements)/len(measurements), 4),
              'elapsed_seconds': round(time.monotonic() - started, 2)}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
