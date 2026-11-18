# Bitcoin Node & Local Explorer

Self-contained Docker Compose deployments providing an unpruned Bitcoin Core node, an Esplora/Electrum address indexer (`mempool/electrs`), a local read-only Mempool web explorer, and a Prometheus + Grafana health dashboard.

Three isolated configurations are included, each using its own Compose project name, Docker volumes, and localhost ports:

| Network | Compose File | Purpose |
|---|---|---|
| **Mainnet** | `compose.mainnet.yml` | Full validating Bitcoin mainnet node and local explorer |
| **Testnet4** | `compose.testnet4.yml` | Live public test network (BIP-94) with smaller footprint |
| **Regtest** | `compose.yml` | Offline private sandbox with automatic synthetic transaction history |

All blockchain lookups, address searches, and transaction views run against your local node and indexer—no third-party explorer APIs are used at runtime.

---

## Architecture

```text
[Bitcoin peers] ──(P2P only on mainnet/testnet4)──> Bitcoin Core (unpruned, txindex=1)
                                                          │
                                                          ▼
                                               mempool/electrs (Esplora + Electrum)
                                                          │
                                                          ▼
                                            Mempool backend ◄──► MariaDB
                                                          │
                                                          ▼
                                              Mempool web (read-only nginx)
                                                          │
                                                          ▼
                                          Localhost gateway (127.0.0.1 only)

Core + electrs + explorer probes ──> status exporter ──> Prometheus ──> Grafana
```

### Key Design Choices
- **Network isolation:** On `mainnet` and `testnet4`, only the `bitcoin` container joins the outbound `p2p` bridge (`8333` / `48333`) to sync blocks and receive live mempool updates. `electrs`, `db`, `api`, `web`, `prometheus`, and `grafana` run on an `internal: true` Docker network with no external route. `regtest` runs completely offline.
- **Read-only explorer:** The frontend nginx config disables external service proxies, enforces a local Content Security Policy, and blocks non-`GET` API requests (`403`) so the explorer cannot broadcast transactions. Fiat prices, external mining-pool updates, and accelerator links are disabled.
- **Esplora indexing (`mempool/electrs`):** Provides full address histories, balances, and spent-output transaction links (`outspends`) so users can trace spending paths directly in the UI.
- **Pinned versions & narrow compatibility patches:** `docker/backend` patches `mempool/backend:v3.2.1` so `testnet4` and `regtest` block endpoints use Bitcoin handlers instead of falling back to Liquid handlers, and creates `/backend/cache` with non-root ownership (`1000:1000`). `docker/frontend` patches address-prefix maps in `mempool/frontend:v3.2.1` for `regtest` (`bcrt1`, `m`/`n`, `2`). Both builds fail loudly if upstream patterns change.

---

## Prerequisites

- **Linux (recommended for production):** Docker Engine + Docker Compose plugin.
- **Windows / macOS:** Docker Desktop with Linux containers (WSL 2 backend on Windows).
- Internet access at install time to pull/build pinned images (and ongoing P2P access for `mainnet` / `testnet4`).

### Hardware & Storage Planning

| Mode | CPU / RAM | Storage Target | Notes |
|---|---|---|---|
| **Mainnet** (`compose.mainnet.yml`) | 6–8 cores, 32+ GB RAM | **2 TB SSD minimum** (4 TB NVMe recommended) | Initial sync + indexing takes days depending on disk and bandwidth. |
| **Testnet4** (`compose.testnet4.yml`) | 2–4 cores, 6–8 GB Docker RAM | ~35–50 GB | Optional `--lightmode` override cuts `electrs` index size roughly in half (`~28 GB` total observed at tip `162k`). |
| **Regtest** (`compose.yml`) | 2–4 cores, 6–8 GB Docker RAM | ~1–2 GB | Generates synthetic transactions locally in minutes. |

---

## Quick Start

Copy `.env.example` to `.env` before first startup if you want to customize ports, credentials, or the regtest dataset size:

```sh
cp .env.example .env
# PowerShell: Copy-Item .env.example .env
```

Change the default passwords in `.env` (`GRAFANA_PASSWORD`, `MAINNET_RPC_PASSWORD`, `MAINNET_DB_PASSWORD`, `MAINNET_DB_ROOT_PASSWORD`) before starting **mainnet**. Changing `GRAFANA_PASSWORD` or database passwords after volumes are initialized does not overwrite existing accounts.

### 1. Mainnet

```sh
docker compose -f compose.mainnet.yml up -d --build
```

| Interface | Default URL |
|---|---|
| Status & sync progress | http://localhost:8095 |
| Mainnet explorer | http://localhost:8094 |
| Grafana health dashboard | http://localhost:3003 |

`electrs` begins serving explorer queries after Bitcoin Core finishes initial block download (`compose.mainnet.yml` mounts `mainnet-bitcoin-data` read-only into `electrs` for faster direct block-file indexing). Check the status page (`http://localhost:8095`) to confirm **Ready to explore** and `lag 0`.

### 2. Testnet4

```sh
docker compose -f compose.testnet4.yml up -d --build
```

For storage-constrained test machines, add the optional `--lightmode` override (`electrs` omits duplicate raw-transaction storage and reads raw transactions from Bitcoin Core's `txindex`):

```sh
docker compose -f compose.testnet4.yml -f compose.testnet4.lightmode.yml up -d --build
```

| Interface | Default URL |
|---|---|
| Status & sync progress | http://localhost:8093 |
| Testnet4 explorer | http://localhost:8092 |
| Grafana health dashboard | http://localhost:3002 |

### 3. Regtest (Offline Sandbox)

```sh
docker compose up -d --build
```

On first startup, the `seed` container automatically creates **25,000** synthetic transactions (`small`: `1,000`, `medium`: `25,000`, `large`: `100,000`, controlled by `DATASET_SIZE` and `DATASET_SEED` in `.env`) covering SegWit, Taproot, wrapped SegWit, legacy addresses, batch payments, consolidations, and spending chains.

| Interface | Default URL |
|---|---|
| Status & clickable examples | http://localhost:8091 |
| Regtest explorer | http://localhost:8090 |
| Grafana health dashboard | http://localhost:3001 |

`seed` exiting with code `0` means generation completed. Wait until `http://localhost:8091` reports **Ready to explore**. Note that `regtest` amounts are synthetic and mainnet-oriented widgets in Mempool (fiat equivalents, fee timing, difficulty/halving estimates) do not apply.

---

## Lifecycle Commands

Use the matching `-f <compose-file>` flag for `testnet4` or `mainnet` (omit `-f` for `regtest`).

**Stop containers while keeping blockchain data and indexes:**
```sh
docker compose down
docker compose -f compose.testnet4.yml down
docker compose -f compose.mainnet.yml down
```

**Resume existing data:**
```sh
docker compose up -d
docker compose -f compose.testnet4.yml up -d
docker compose -f compose.mainnet.yml up -d
```

**Full reset (deletes only that network's volumes, chain data, indexes, and DB state):**
```sh
docker compose down --volumes
```

Avoid global Docker prune commands (`docker system prune --volumes`) if other projects share the host.

---

## Verification

After `regtest` reports ready (`http://localhost:8091`), run the automated integration check:

```sh
docker compose exec -T lab python /app/verify.py
```

This verifies explorer transactions and `outspends` links against Bitcoin Core, checks all four address formats, walks every pagination page of the high-activity address against Electrum, confirms read-only `POST` rejection (`403`), and checks Prometheus targets.

Host-only unit and Compose validation checks:

```sh
python -m unittest discover -s tests -v
docker compose config --quiet
docker compose -f compose.testnet4.yml config --quiet
docker compose -f compose.testnet4.yml -f compose.testnet4.lightmode.yml config --quiet
docker compose -f compose.mainnet.yml config --quiet
```

---

## Monitoring & Troubleshooting

Grafana login defaults to `admin` / `regtest-dashboard` (set `GRAFANA_PASSWORD` in `.env`). The pre-provisioned **Bitcoin Regtest Lab** dashboard monitors `lab_ready`, node height, `electrs` index height, indexing lag, RPC availability, block/undo storage, and explorer probe latency. Prometheus retains at most 3 days / 256 MB, and container logs rotate at `10 MB x 2`.

- **Port already in use:** Override the relevant `*_PORT` variables in `.env`.
- **Explorer searches return nothing while starting:** Check the status guide URL first; `electrs` only opens queries once Bitcoin Core finishes initial block download and initial indexing completes.
- **Changing `DATASET_SIZE` / `DATASET_SEED` in regtest:** Existing completed data is preserved; run `docker compose down --volumes` before switching presets.
- **Transient gateway errors after recreate:** Internal nginx DNS refreshes every 5 seconds while containers restart.

---

## Licenses

All third-party components retain their respective upstream licenses, including Bitcoin Core (MIT), `mempool/electrs` (MIT), Mempool backend/frontend (AGPL-3.0), MariaDB (GPL-2.0), Prometheus (Apache-2.0), and Grafana (AGPL-3.0). Patch scripts and Docker build definitions are included in `docker/`.
