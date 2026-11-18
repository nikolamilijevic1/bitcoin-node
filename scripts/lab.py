"""Read-only local status guide and Prometheus exporter; no third-party packages."""
import html
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rpc import rpc, electrum

ROOT = Path('/dataset')
MODE = os.environ.get('LAB_MODE', 'regtest')
EXPLORER = 'http://localhost:' + os.environ.get('EXPLORER_PORT', '8090')
GRAFANA = 'http://localhost:' + os.environ.get('GRAFANA_PORT', '3001')
cached = {'metrics': '', 'status': {}}

NETWORK_DESCRIPTIONS = {
    'testnet4': (
        'Bitcoin testnet4 node',
        'Live public test network (BIP-94). Test coins have no monetary value.',
        'Only Bitcoin Core connects to public testnet4 peers (TCP 48333) for blocks and live mempool updates.',
    ),
    'mainnet': (
        'Bitcoin mainnet node',
        'Full validating Bitcoin mainnet node with local read-only explorer and health monitoring.',
        'Only Bitcoin Core connects to public Bitcoin peers (TCP 8333) for blocks and live mempool updates.',
    ),
}


def state():
    if MODE != 'regtest':
        return {}
    try:
        return json.loads((ROOT / 'state.json').read_text())
    except (OSError, ValueError):
        return {}


def collect():
    while True:
        values = {'bitcoin_rpc_up': 0, 'electrs_rpc_up': 0, 'explorer_api_up': 0}
        try:
            info = rpc('getblockchaininfo')
            values.update(bitcoin_rpc_up=1, bitcoin_blocks=info['blocks'],
                          bitcoin_headers=info['headers'], bitcoin_disk_bytes=info['size_on_disk'],
                          bitcoin_initial_block_download=int(info['initialblockdownload']),
                          bitcoin_verification_progress=round(info.get('verificationprogress', 0.0), 6))
            values['bitcoin_mempool_transactions'] = rpc('getmempoolinfo')['size']
            values['bitcoin_peers'] = rpc('getnetworkinfo')['connections']
        except Exception:
            pass
        try:
            tip = electrum('blockchain.headers.subscribe')
            values.update(electrs_rpc_up=1, electrs_height=tip['height'])
            if 'bitcoin_blocks' in values:
                values['bitcoin_index_lag'] = max(0, values['bitcoin_blocks'] - tip['height'])
        except Exception:
            pass
        started = time.monotonic()
        try:
            with urllib.request.urlopen('http://api:8999/api/v1/backend-info', timeout=5) as response:
                json.load(response)
            with urllib.request.urlopen('http://web:8080/api/blocks/tip/height', timeout=5) as response:
                height = int(response.read())
            values.update(explorer_api_up=1, explorer_height=height,
                          explorer_probe_seconds=time.monotonic() - started)
        except Exception:
            pass
        if MODE == 'regtest':
            data = state()
            values.update(dataset_transactions=data.get('completed', 0), dataset_target=data.get('target', 0),
                          dataset_complete=int(data.get('status') == 'complete'))
            values['lab_ready'] = int(values['dataset_complete'] and values['bitcoin_rpc_up'] and
                                      values['electrs_rpc_up'] and values['explorer_api_up'] and
                                      values.get('bitcoin_index_lag', 1) == 0 and
                                      values.get('explorer_height') == values.get('bitcoin_blocks'))
        else:
            values['lab_ready'] = int(values['bitcoin_rpc_up'] and values['electrs_rpc_up'] and
                                      values['explorer_api_up'] and
                                      values.get('bitcoin_initial_block_download', 1) == 0 and
                                      values.get('bitcoin_index_lag', 1) == 0 and
                                      values.get('explorer_height') == values.get('bitcoin_blocks'))
        cached['status'] = values
        cached['metrics'] = ''.join(f'# TYPE {key} gauge\n{key} {value}\n' for key, value in values.items())
        time.sleep(5)


def render_live_node():
    title, subtitle, p2p_note = NETWORK_DESCRIPTIONS.get(
        MODE,
        (f'Bitcoin {MODE} node', 'Local read-only explorer and health monitor.', 'Only Bitcoin Core connects to peers.'),
    )
    st = cached['status']
    ready = bool(st.get('lab_ready'))
    pct = st.get('bitcoin_verification_progress', 0.0) * 100
    ibd = st.get('bitcoin_initial_block_download', 1)
    status_label = 'Ready to explore' if ready else ('Initial block download in progress' if ibd else 'Indexing — refresh to check progress')
    disk_mib = st.get('bitcoin_disk_bytes', 0) / (1024 * 1024)
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(title)} — status</title><style>
body{{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;background:#101820;color:#edf2f7}}
a{{color:#8fd5ff}}.status{{padding:16px;background:#243746;border-radius:8px;line-height:1.6}}
small{{color:#b8c8d8}}</style>
<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p>
<p><a href="{EXPLORER}">Open explorer</a> · <a href="{GRAFANA}">Open health dashboard</a></p>
<p class="status"><strong>{status_label}</strong><br>
Sync progress: {pct:.2f}% · node height {st.get('bitcoin_blocks', 'unknown')} / headers {st.get('bitcoin_headers', 'unknown')}<br>
Index height: {st.get('electrs_height', 'unknown')} (lag {st.get('bitcoin_index_lag', 'unknown')}) ·
explorer height: {st.get('explorer_height', 'unknown')} ·
mempool: {st.get('bitcoin_mempool_transactions', 'unknown')} txs ·
peers: {st.get('bitcoin_peers', 'unknown')} ·
block/undo disk: {disk_mib:.1f} MiB</p>
<h2>Network isolation</h2><ul>
<li>{html.escape(p2p_note)}</li>
<li>Address, transaction, and block searches stay inside the local Docker network (<code>electrs</code> + <code>mempool</code>).</li>
</ul>
<p><small>Refresh this page while syncing or indexing. Grafana login: admin; password configured in .env.</small></p></html>'''


def render_regtest():
    data = state()
    e = html.escape
    ready = bool(cached['status'].get('lab_ready'))
    rows = ''.join('<tr><td>' + e(item['scenario']) + '</td><td><a href="' + EXPLORER + '/tx/' +
                   e(item['txid']) + '">' + e(item['txid']) + '</a></td></tr>'
                   for item in data.get('examples', []))
    addresses = ''.join('<li><a href="' + EXPLORER + '/address/' + e(address) + '">' +
                        e(address) + '</a></li>' for address in data.get('addresses', [])[:8])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Bitcoin regtest lab — examples</title><style>
body{{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;background:#101820;color:#edf2f7}}
a{{color:#8fd5ff}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #425466}}td{{overflow-wrap:anywhere}}
table{{width:100%;table-layout:fixed}}th:first-child{{width:25%}}li{{margin:12px 0;overflow-wrap:anywhere}}
.status{{padding:16px;background:#243746;border-radius:8px}}small{{color:#b8c8d8}}</style>
<h1>Bitcoin regtest lab</h1><p>Private synthetic transactions. No real bitcoin.</p>
<p><a href="{EXPLORER}">Open explorer</a> · <a href="{GRAFANA}">Open health dashboard</a></p>
<p class="status">{'Ready to explore' if ready else 'Preparing — refresh to check progress'} ·
{data.get('completed', 0):,} / {data.get('target', 0):,} generated transactions ·
node height {cached['status'].get('bitcoin_blocks', 'unknown')} ·
index height {cached['status'].get('electrs_height', 'unknown')}</p>
<h2>Try these searches</h2><p>The first address receives a payment every five generated transactions.
The remaining examples cover native SegWit, Taproot, wrapped SegWit, and legacy addresses.</p><ul>{addresses}</ul>
<h2>Follow a spending path</h2><p>Open a payment below. Recipient outputs come first; the final output is the
generator's continuing spending path. Follow its spending transaction using the explorer's spent-output link.
Consolidation examples combine two paths and split the remainder into two continuing paths.
This explanation comes from our generator; these labels are not encoded in Bitcoin transactions.</p>
<table><thead><tr><th>Scenario</th><th>Transaction</th></tr></thead><tbody>{rows}</tbody></table>
<p><small>Refresh this page while generation is running. The node, indexer, and explorer must all catch up.
Grafana login: admin; password configured in .env (default documented in README).</small></p></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/metrics':
            return self.reply(cached['metrics'], 'text/plain; version=0.0.4')
        if self.path == '/health':
            return self.reply(json.dumps(cached['status']), 'application/json')
        if self.path != '/':
            return self.reply('Not found', 'text/plain', 404)
        body = render_regtest() if MODE == 'regtest' else render_live_node()
        self.reply(body, 'text/html; charset=utf-8')

    def reply(self, content, content_type, status=200):
        encoded = content.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == '__main__':
    threading.Thread(target=collect, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 9100), Handler).serve_forever()
