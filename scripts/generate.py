"""Bounded, resumable synthetic history. Wallets and secrets are for regtest only."""
import json
import os
import random
import time
from pathlib import Path

from rpc import rpc, rpc_batch, require_regtest

ROOT = Path(os.environ.get('DATASET_DIR', '/dataset'))
PRESETS = {'small': 1000, 'medium': 25000, 'large': 100000}
WALLET = 'lab-generator'
FEE = 2000  # sats; deliberately generous for these synthetic transactions


def save(name, obj):
    temp = ROOT / (name + '.tmp')
    temp.write_text(json.dumps(obj, separators=(',', ':')))
    temp.replace(ROOT / name)


def btc(sats):
    return round(sats / 100_000_000, 8)


def plan_transaction(state):
    """Select explicit UTXOs: no hidden wallet coin-selection assumptions."""
    n = state['completed']
    rng = random.Random(state['seed'] + n)
    first = n % len(state['lanes'])
    indices = [first]
    scenario = 'payment-with-change'
    if n % 50 == 0:
        indices = [first, (first + 1) % len(state['lanes'])]
        scenario = 'consolidation-and-resplit'
    lanes = [state['lanes'][i] for i in indices]
    total = sum(lane['sats'] for lane in lanes)
    recipients = [state['addresses'][0]] if n % 5 == 0 else [rng.choice(state['addresses'][1:])]
    if n % 50 == 1:
        recipients = rng.sample(state['addresses'][1:], 10)
        scenario = 'batch-payment'
    payment = 10000
    remainder = total - FEE - len(recipients) * payment
    if remainder <= 0:
        raise RuntimeError('Dataset exhausted its funding; reset or reduce size')
    outputs = [{address: btc(payment)} for address in recipients]
    replacements = []
    for pos, (index, lane) in enumerate(zip(indices, lanes)):
        amount = remainder // len(indices) + (remainder % len(indices) if pos == 0 else 0)
        replacements.append({'index': index, 'vout': len(outputs), 'sats': amount,
                             'address': lane['address']})
        outputs.append({lane['address']: btc(amount)})
    inputs = [{'txid': lane['txid'], 'vout': lane['vout']} for lane in lanes]
    return inputs, outputs, replacements, scenario, recipients


def plan_batch(state):
    """Only batch transactions using disjoint inputs; stop at a mining boundary."""
    plans, used = [], set()
    limit = min(64, state['target'] - state['completed'], 200 - state['completed'] % 200)
    for offset in range(limit):
        candidate = dict(state, completed=state['completed'] + offset)
        plan = plan_transaction(candidate)
        indices = {r['index'] for r in plan[2]}
        if used.intersection(indices):
            break
        plans.append(plan)
        used.update(indices)
    return plans


def run():
    ROOT.mkdir(parents=True, exist_ok=True)
    size = os.environ.get('DATASET_SIZE', 'medium')
    if size not in PRESETS:
        raise ValueError('DATASET_SIZE must be small, medium, or large')
    seed = int(os.environ.get('DATASET_SEED', '2026'))
    target = PRESETS[size]
    require_regtest()
    state_path = ROOT / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['target'] != target or state['seed'] != seed:
            raise RuntimeError('Existing dataset has different settings. Reset explicitly before changing preset/seed.')
        if state.get('status') == 'complete':
            # Catch accidentally retained metadata paired with a replaced blockchain.
            if rpc('getblockhash', [state['height']]) != state['tip_hash']:
                raise RuntimeError('Saved dataset does not match the active blockchain')
            print('Dataset already complete; reusing persistent history.', flush=True)
            return
        print(f"Resuming at {state['completed']}/{target}", flush=True)
    else:
        if rpc('getblockcount') != 0:
            raise RuntimeError('Unrecognized nonempty chain. Refusing to generate over existing history.')
        state = {'version': 1, 'status': 'initializing', 'seed': seed, 'target': target,
                 'completed': 0, 'started': time.time(), 'examples': [], 'lanes': [], 'addresses': []}
        save('state.json', state)
    if WALLET not in rpc('listwallets'):
        names = [w['name'] for w in rpc('listwalletdir')['wallets']]
        rpc('loadwallet' if WALLET in names else 'createwallet', [WALLET])
    if state['status'] == 'generating' and not state.get('pending') and rpc('getrawmempool'):
        rpc('generatetoaddress', [1, state['mining_address']])
    if state['status'] == 'initializing':
        # These stages may be safely repeated after interruption; unused addresses are harmless.
        if not state.get('mining_address'):
            state['mining_address'] = rpc('getnewaddress', ['mining', 'bech32'], WALLET)
            save('state.json', state)
        height = rpc('getblockcount')
        if height < 220:
            rpc('generatetoaddress', [220 - height, state['mining_address']])
        coins = rpc('listunspent', [100], WALLET)
        coins = sorted(coins, key=lambda c: (c['txid'], c['vout']))[:64]
        if len(coins) != 64:
            raise RuntimeError('Insufficient mature funding outputs')
        state['lanes'] = [dict(txid=c['txid'], vout=c['vout'], sats=round(c['amount'] * 100_000_000),
                               address=rpc('getnewaddress', ['path', 'bech32'], WALLET)) for c in coins]
        state['addresses'] = [rpc('getnewaddress', ['recipient', kind], WALLET)
                              for kind in ['bech32', 'bech32m', 'p2sh-segwit', 'legacy'] * 64]
        state['status'] = 'generating'
        save('state.json', state)
    while state['completed'] < target:
        if not state.get('pending'):
            plans = plan_batch(state)
            raws = rpc_batch([('createrawtransaction', [p[0], p[1]]) for p in plans])
            signed = rpc_batch([('signrawtransactionwithwallet', [raw]) for raw in raws], WALLET)
            if not all(tx['complete'] for tx in signed):
                raise RuntimeError('Transaction signing incomplete')
            state['pending'] = [{'hex': tx['hex'], 'replacements': p[2],
                                 'scenario': p[3], 'inputs': p[0], 'recipients': p[4]}
                                for tx, p in zip(signed, plans)]
            save('state.json', state)  # write-ahead record before broadcast
        pending_batch = state['pending'] if isinstance(state['pending'], list) else [state['pending']]
        results = rpc_batch([('sendrawtransaction', [p['hex']]) for p in pending_batch], allow_errors=True)
        for pending, result in zip(pending_batch, results):
            if result.get('error'):
                # A process can stop after broadcast but before saving the resulting txid.
                txid = rpc('decoderawtransaction', [pending['hex']])['txid']
                rpc('getrawtransaction', [txid])  # do not swallow genuine rejection
            else:
                txid = result['result']
            for replacement in pending['replacements']:
                state['lanes'][replacement['index']] = {k: v for k, v in replacement.items() if k != 'index'}
                state['lanes'][replacement['index']]['txid'] = txid
            if state['completed'] < 70 or state['completed'] % 1000 == 0:
                state['examples'].append({'txid': txid, 'scenario': pending['scenario'],
                                          'inputs': pending['inputs'], 'recipients': pending['recipients']})
            state['completed'] += 1
        state.pop('pending')
        save('state.json', state)
        if state['completed'] % 200 == 0 or state['completed'] == target:
            rpc('generatetoaddress', [1, state['mining_address']])
            print(f"Generated {state['completed']:,}/{target:,} transactions; block {rpc('getblockcount')}", flush=True)
    # Also handles interruption after saving the final transaction but before mining it.
    if rpc('getrawmempool'):
        rpc('generatetoaddress', [1, state['mining_address']])
    info = require_regtest()
    state.update(status='complete', finished=time.time(), height=info['blocks'], tip_hash=info['bestblockhash'])
    save('state.json', state)
    print(f"Complete: {target:,} transactions in {time.time() - state['started']:.1f}s. Open the local guide.", flush=True)


if __name__ == '__main__':
    # Kernel lock is released on crash and prevents simultaneous generator runs.
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / '.generator.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run()
