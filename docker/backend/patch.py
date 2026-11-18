"""Narrow compatibility patch for pinned Mempool 3.2.1 backend on regtest/testnet4.

Mempool 3.2.1 treats networks outside ['mainnet', 'testnet', 'signet'] as Liquid
in block listing/lookup handlers and skips assigning extras.pool, which causes the
Mempool frontend /blocks view to throw and retry indefinitely. Add 'testnet4' and
'regtest' to those exact Bitcoin network checks and fail the build if upstream
changes them.
"""
import shutil
import sys
from pathlib import Path

OLD = "['mainnet', 'testnet', 'signet']"
NEW = "['mainnet', 'testnet', 'testnet4', 'signet', 'regtest']"

TARGETS = {
    Path('blocks.js'): 4,
    Path('bitcoin') / 'bitcoin.routes.js': 2,
}


def patch_tree(original: Path, output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(original, output)
    for rel, expected in TARGETS.items():
        path = output / rel
        before = path.read_text()
        count = before.count(OLD)
        if count != expected:
            raise RuntimeError(f'Pinned backend changed in {rel}: expected {expected}, found {count}')
        path.write_text(before.replace(OLD, NEW))
        print(f'Patched {count} network checks in {rel}')


if __name__ == '__main__':
    patch_tree(Path(sys.argv[1]), Path(sys.argv[2]))
