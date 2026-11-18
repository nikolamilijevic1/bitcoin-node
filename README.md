# Bitcoin Regtest Lab

A private Bitcoin blockchain, local transaction/address explorer, realistic synthetic
transaction generator, and operational dashboard. Each person runs an independent
Docker Compose deployment. No public blockchain API is required at runtime.

**Regtest only. The coins have no value. This configuration is not a production/mainnet deployment.**

## Start

Install Docker Engine with Compose on Linux, or Docker Desktop using Linux containers
on Windows/macOS. On Windows, use the WSL 2 backend with approximately 6–8 GB available
to Docker. Check your actual free disk space before starting; leave space for the OS.

From this directory:

```sh
docker compose up -d --build
```

The first build downloads pinned images and applies a small regtest compatibility
patch to the explorer. The generator automatically creates **25,000 transactions**.
Open the guide while it runs; refresh to see progress. Initial database setup and
indexing can lag behind transaction generation.

| Interface | Default URL |
|---|---|
| Start here: status and example searches | http://localhost:8091 |
| Transaction and address explorer | http://localhost:8090 |
| Health dashboard | http://localhost:3001 |

Grafana login: **admin** / **regtest-dashboard**. Set `GRAFANA_PASSWORD` in `.env`
before the first startup to choose a different initial password. Changing that variable
after Grafana has initialized its volume does not change the existing account password.

`seed` exiting with code 0 means generation completed successfully, not a failure.
The guide says **Ready to explore** only when generation is complete and the node,
indexer, and explorer have caught up.

## Explore the dataset

1. Open the guide and click its first address: this is the deliberately busy address.
2. Open a **payment-with-change** example.
3. Inspect the inputs and outputs. The final output continues one of the generated paths.
4. Follow the explorer's spent-output link to the transaction that spends it.
5. Try **batch-payment** and **consolidation-and-resplit** examples.

You can paste transaction IDs and regtest addresses into the explorer search box.
Search blocks by height, or follow block links. The upstream search's block-hash heuristic
assumes mainnet proof-of-work; arbitrary regtest block hashes may be interpreted as
transaction IDs. Direct `/block/<hash>` links work.

Amounts are synthetic BTC/satoshis. Ignore fiat equivalents, fee timing, difficulty,
halving estimates, and other mainnet-oriented dashboard predictions in Mempool:
prices are disabled and regtest blocks are generated on demand. Use Grafana for lab health.
All transactions end up confirmed; no continuous background miner runs after seeding.

## Dataset presets

Copy `.env.example` to `.env` to customize settings (PowerShell: `Copy-Item .env.example .env`).

| `DATASET_SIZE` | Non-coinbase transactions | Use |
|---|---:|---|
| `small` | 1,000 | Quick functional checks |
| `medium` | 25,000 | Default exploration dataset |
| `large` | 100,000 | Opt-in stress trial |

`DATASET_SEED` controls scenario selection. Wallet keys, addresses, block hashes, and
transaction IDs differ across fresh runs. This is repeatable scenario generation,
not byte-for-byte deterministic blockchain generation.

The generator uses 64 continuing spending paths and 256 recipient addresses spanning
native SegWit, Taproot, wrapped SegWit, and legacy formats. Every fifth payment targets
the busy address. Every 50th transaction combines two inputs and resplits the remainder;
the next transaction pays ten recipients. Other transactions make a payment plus change.
Recipient outputs remain unspent; continuing-path outputs are spent repeatedly.
Thus this version tests receiving/address recognition for all four types, while the
continuing paths use native SegWit. It does not cover every possible Bitcoin script.

The node first creates 220 funding/maturity blocks, then mines approximately every
200 generated transactions. Coinbase transactions are additional to preset counts.
There is no need to fill gigabytes merely to create useful transaction histories.
Independent transactions are submitted in bounded RPC batches, with checkpoints before
broadcast, to avoid unnecessary request overhead on workstation hardware.

Generation checkpoints include a write-ahead record before broadcast. If the process
is interrupted, start `seed` again with the same settings:

```sh
docker compose start seed
docker compose logs -f seed
```

A completed dataset is reused on startup. Different preset/seed settings are rejected
against existing data: reset explicitly or use another Compose project with different ports.
The checkpoint logic handles process interruption; it is not a substitute for backups
against disk loss or corruption. Do not manually spend the generator's continuing outputs
while generation is running.

## Stop, restart, and reset

Stop services while retaining all data:

```sh
docker compose down
```

Resume:

```sh
docker compose up -d
```

**Reset deletes this project's synthetic blockchain, wallets, indexes, explorer database,
and monitoring/dashboard state.** Do this only when you intend to start a new dataset:

```sh
docker compose down --volumes
docker compose up -d --build
```

If using `-p <name>` for a separate project, use that same name for every command.
Do not use global Docker prune commands: other projects may exist on the machine.

## Verify

After the guide reports ready:

```sh
docker compose exec -T lab python /app/verify.py
```

This compares explorer transaction values and inputs against Bitcoin Core, follows
spending links, checks spent/unspent outputs, checks all four address formats,
walks every page of the busy address's history against the indexer's independent
Electrum history response, checks chain counts, and checks monitoring targets.

Host-only unit checks, if Python is installed:

```sh
python -m unittest discover -s tests -v
docker compose config --quiet
```

## Architecture and intentional choices

```text
Bitcoin Core -> mempool/electrs (Esplora API + Electrum protocol)
                      |                  |
                      +--> Mempool <----> MariaDB
                               |
                     local browser gateway

Core + indexer + explorer probes -> lab exporter -> Prometheus -> Grafana
Dataset generator -> Core; local guide reads generator checkpoints
```

The Esplora-capable **mempool/electrs** fork is intentional. The original
`romanz/electrs` through Mempool's Electrum backend can report an output as spent
without returning the spending transaction ID. Esplora supplies the links needed
to follow spending paths. Its indexes have different, generally higher mainnet storage
requirements; earlier small-index estimates for romanz/electrs do not apply to this stack.
Mainnet sizing and hardening remain future work.

Images are pinned by version. The frontend Dockerfile additionally patches two
address-prefix maps in the pinned Mempool 3.2.1 frontend, which otherwise does not
recognize regtest addresses in native search/type displays. The patch changes the
single-network default from mainnet address prefixes to regtest prefixes, preserves
upstream notices, and fails if the expected patterns disappear. Review it when upgrading.
The unmodified upstream project is https://github.com/mempool/mempool/tree/v3.2.1.

All data services join an **internal Docker network** without an external route.
Only nginx gateway joins a regular bridge to publish three **127.0.0.1-only** ports;
it proxies fixed local services. Node RPC, databases, indexer, and Prometheus are
not published. Frontend third-party services are disabled/removed from proxy routing,
and a browser content security policy restricts automatic resource requests.
The explorer proxy blocks non-GET API requests; upstream broadcast/test forms remain
visible but are intentionally unavailable through this read-only interface.
Upstream documentation/footer links may still navigate away if clicked.
Image pulls/builds require internet access at installation time.

The fixed RPC/database credentials are public development defaults inside this isolated
regtest deployment. Never connect this configuration to real wallets or expose it to
a LAN/public network. Changing only the network flag is not a supported mainnet migration.

## Monitoring and storage

Grafana is provisioned automatically with readiness, generation progress, node/indexer
heights, lag, RPC availability, block-file size, and explorer height-probe latency.
Probe latency is not a benchmark of arbitrary address searches. Node block storage
is not the total deployment size, and Docker VM free space is not Windows C: free space.

Prometheus retains at most three days / approximately 256 MB of sample blocks (WAL
and other overhead are additional). Container logs rotate at 10 MB x 2 per service.
Services have individual memory limits totaling approximately 5.7 GB; the host needs
additional Docker/OS memory. Data lives in named Docker volumes, not Windows source folders.

Useful commands:

```sh
docker compose ps -a
docker compose logs --tail 50 seed electrs api
docker stats --no-stream
docker system df -v
```

Troubleshooting:

- **Port already in use:** change `EXPLORER_PORT`, `GUIDE_PORT`, or `GRAFANA_PORT` in `.env`.
- **Generator exited 1:** read `docker compose logs seed`; fix the reported issue, then
  `docker compose start seed`. Existing preset mismatch requires an intentional reset.
- **Search is empty:** check the guide's readiness and index height before drawing conclusions.
- **Services recreated:** internal proxy DNS refreshes every five seconds; briefly unavailable
  services may produce a transient gateway error while restarting.
- **Old frontend in browser:** reload without cache after rebuilding the compatibility patch.
- **Docker unavailable:** start Docker Desktop and select Linux containers.
- **Disk pressure:** stop the stack, inspect disk use, and reset only this disposable project if desired.

No case management, attribution, clustering, evidence exports, Ethereum, or historical
mempool archive is included. This is a development lab, not a forensic attribution product.

## Testnet4 (live public test network)

An isolated `testnet4` deployment is provided in `compose.testnet4.yml` (`bitcoin-testnet4-lab`)
using separate Docker volumes and separate localhost ports so it does not overwrite `regtest`:

```sh
docker compose -f compose.testnet4.yml up -d --build
```

On storage-constrained test machines, add the optional `--lightmode` override (omits duplicate
raw transaction storage in `electrs` and reads raw transactions from Bitcoin Core's `txindex`):

```sh
docker compose -f compose.testnet4.yml -f compose.testnet4.lightmode.yml up -d --build
```

| Interface | Default URL |
|---|---|
| Status guide (sync & index progress) | http://localhost:8093 |
| Testnet4 explorer | http://localhost:8092 |
| Health dashboard | http://localhost:3002 |

Unlike `regtest`, `bitcoin` joins a `p2p` bridge for outbound peer synchronization and live
mempool/block updates (`testnet4`, TCP 48333). `electrs`, `db`, `api`, `web`, `prometheus`,
and `grafana` remain on the internal Docker network without outbound internet access.
`electrs` begins serving queries once Bitcoin Core finishes initial block download.

Stop or reset only the `testnet4` stack:

```sh
docker compose -f compose.testnet4.yml down
docker compose -f compose.testnet4.yml down --volumes  # deletes testnet4 chain & indexes
```

## Sharing and upstream licenses

Share this repository, not Docker volumes or generated wallets. `.gitignore` excludes
local settings and temporary files. A GitHub remote has not been configured automatically.
Third-party software retains its own licenses, including Mempool's AGPL license and
Grafana's applicable license. The frontend patch source and build instructions are
included; review upstream redistribution obligations before distributing built images.
