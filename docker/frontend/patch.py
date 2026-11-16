"""Narrow compatibility patch for the pinned, single-network regtest frontend.

Mempool 3.2.1 backend supports regtest, but the default frontend address maps
recognize mainnet prefixes. Adapt only the two exact address-map shapes;
fail the build if upstream changes them. No transaction or amount logic changes.
The original image and all attribution/license notices remain intact.
"""
import re
import sys
from pathlib import Path

SEARCH = re.compile(r'mainnet:\{base58:"\[13\]"\+([\w$]+)\+"\{26,33\}",bech32:"\(\?:bc1"\+([\w$]+)\+"\{6,100\}\|BC1"\+([\w$]+)\+"\{6,100\}\)"\}')
TYPE = 'mainnet:{base58:{pubkey:["1"],script:["3"]},bech32:"bc1"}'


def patch(text):
    text, count = SEARCH.subn(lambda m: 'mainnet:{base58:"[mn2]"+' + m[1] +
        '+"{25,34}",bech32:"(?:bcrt1"+' + m[2] + '+"{6,100}|BCRT1"+' + m[3] + '+"{6,100})"}', text)
    kinds = text.count(TYPE)
    text = text.replace(TYPE, 'mainnet:{base58:{pubkey:["m","n"],script:["2"]},bech32:"bcrt1"}')
    return text, count, kinds


if __name__ == '__main__':
    original, output = map(Path, sys.argv[1:])
    searches = types = 0
    for file in original.rglob('*.js'):
        before = file.read_text()
        after, a, b = patch(before)
        searches += a
        types += b
        if after != before:
            dest = output / file.relative_to(original)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(after)
    if searches == 0 or types == 0:
        raise RuntimeError('Pinned frontend changed: review regtest address compatibility patch')
    print(f'Patched {searches} search maps and {types} address-type maps')
