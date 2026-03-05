#!/usr/bin/env python3
"""
Memory stress test for BrevilleWsClient.

Runs a local WebSocket server that floods the client with state reports and
periodically drops connections to trigger reconnect logic. Prints memory and
task snapshots at regular intervals, then exits hard to avoid cleanup hangs.

Usage:
    source venv/bin/activate
    python tests/memory_stress.py [--duration 120] [--msg-interval 0.02] [--disconnect-interval 10]
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psutil
from websockets.asyncio.server import serve

from sagecoffee import ws_client as ws_client_module
from sagecoffee.ws_client import BrevilleWsClient

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 18765
WS_URL_LOCAL = f"ws://{SERVER_HOST}:{SERVER_PORT}"
SERIAL = "STRESS001234567890"

DEFAULT_DURATION = 90
DEFAULT_MSG_INTERVAL = 0.02
DEFAULT_DISCONNECT_INTERVAL = 10
SNAPSHOT_INTERVAL = 10


# ─────────────────────────────── server ───────────────────────────────────────

_connections: list = []
_msgs_sent = 0
_conn_count = 0


async def server_handler(websocket) -> None:
    global _conn_count, _msgs_sent
    _conn_count += 1
    cid = _conn_count
    _connections.append(websocket)
    print(f"  [server] conn #{cid}  (active: {len(_connections)})", flush=True)
    try:
        seq = 0
        while True:
            await websocket.send(json.dumps({
                "serialNumber": SERIAL,
                "messageType": "stateReport",
                "version": seq,
                "data": {
                    "reported": {
                        "state": "ready",
                        "boiler": [
                            {"cur_temp": 93.5 + seq * 0.0001, "temp_sp": 94.0},
                            {"cur_temp": 140.0, "temp_sp": 140.0},
                        ],
                        "grind.size_setting": 15,
                    },
                    "desired": {"state": "ready"},
                },
            }))
            seq += 1
            _msgs_sent += 1
            await asyncio.sleep(DEFAULT_MSG_INTERVAL)
    except Exception:
        pass
    finally:
        if websocket in _connections:
            _connections.remove(websocket)
        print(f"  [server] conn #{cid} closed (active: {len(_connections)})", flush=True)


async def periodic_disconnect(interval: float) -> None:
    await asyncio.sleep(interval)
    while True:
        n = len(_connections)
        if n:
            print(f"  [server] force-closing {n} conn(s)", flush=True)
            for ws in list(_connections):
                try:
                    await ws.close()
                except Exception:
                    pass
        await asyncio.sleep(interval)


# ─────────────────────────────── client ───────────────────────────────────────

_msg_count = 0
_reconnect_count = 0


async def get_token() -> str:
    return "fake_id_token"


def patch_reconnect(client: BrevilleWsClient) -> None:
    """Patch reconnect to use short initial delay and count calls."""
    orig = BrevilleWsClient._reconnect_with_backoff

    async def fast_reconnect(self_: BrevilleWsClient) -> None:
        global _reconnect_count
        _reconnect_count += 1
        # Use a very short delay so test doesn't stall too long
        self_._reconnect_delay = min(self_._reconnect_delay, 0.5)
        await orig(self_)

    BrevilleWsClient._reconnect_with_backoff = fast_reconnect  # type: ignore[method-assign]


async def client_loop() -> None:
    global _msg_count
    client = BrevilleWsClient(get_id_token=get_token, ping_interval=20)
    client._appliances.append((SERIAL, "stressApp", "BES995"))
    patch_reconnect(client)
    async for _msg in client.listen():
        _msg_count += 1


# ────────────────────────────── monitoring ────────────────────────────────────

def print_snapshot(
    proc: psutil.Process,
    baseline: tracemalloc.Snapshot,
    elapsed: float,
) -> tracemalloc.Snapshot:
    gc.collect()
    current = tracemalloc.take_snapshot()

    rss_mb = proc.memory_info().rss / 1024 / 1024
    tasks = len(asyncio.all_tasks())

    print(f"\n{'─'*64}", flush=True)
    print(f"  t={elapsed:5.0f}s  msgs={_msg_count:,}  reconnects={_reconnect_count}"
          f"  tasks={tasks}  RSS={rss_mb:.1f} MB", flush=True)

    stats = current.compare_to(baseline, "lineno")
    if stats:
        print("  tracemalloc growth since baseline:", flush=True)
        for s in stats[:8]:
            print(f"    {s}", flush=True)

    counts: dict[str, int] = {}
    for obj in gc.get_objects():
        t = type(obj).__name__
        counts[t] = counts.get(t, 0) + 1
    top5 = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"  gc top types: {top5}", flush=True)

    # Report active asyncio tasks by name/coro
    all_tasks = list(asyncio.all_tasks())
    print(f"  asyncio tasks ({len(all_tasks)} total):", flush=True)
    task_names: dict[str, int] = {}
    for t in all_tasks:
        name = t.get_coro().__qualname__ if hasattr(t.get_coro(), '__qualname__') else str(t)
        task_names[name] = task_names.get(name, 0) + 1
    for name, cnt in sorted(task_names.items(), key=lambda x: x[1], reverse=True):
        print(f"    {cnt}x {name}", flush=True)

    print(f"{'─'*64}", flush=True)
    return current


async def monitor(proc: psutil.Process, duration: float) -> None:
    gc.collect()
    tracemalloc.start(25)
    base = tracemalloc.take_snapshot()
    start = asyncio.get_running_loop().time()
    last = start

    rss0 = proc.memory_info().rss / 1024 / 1024
    print(f"\n{'='*64}", flush=True)
    print(f"  Baseline RSS: {rss0:.1f} MB", flush=True)
    print(f"  duration={duration}s  msg_interval={DEFAULT_MSG_INTERVAL}s"
          f"  snapshot_interval={SNAPSHOT_INTERVAL}s", flush=True)
    print(f"{'='*64}", flush=True)

    while True:
        await asyncio.sleep(1)
        now = asyncio.get_running_loop().time()
        if now - last >= SNAPSHOT_INTERVAL:
            base = print_snapshot(proc, base, now - start)
            last = now
        if now - start >= duration:
            break

    # Final snapshot
    rss_mb = proc.memory_info().rss / 1024 / 1024
    print(f"\n{'='*64}", flush=True)
    print(f"  DONE  t={now-start:.0f}s  msgs={_msg_count:,}  "
          f"reconnects={_reconnect_count}  RSS={rss_mb:.1f} MB", flush=True)
    print(f"{'='*64}", flush=True)


# ─────────────────────────────── main ────────────────────────────────────────

async def main(duration: float, msg_interval: float, disconnect_interval: float) -> None:
    global DEFAULT_MSG_INTERVAL
    DEFAULT_MSG_INTERVAL = msg_interval

    ws_client_module.WS_URL = WS_URL_LOCAL
    server = await serve(server_handler, SERVER_HOST, SERVER_PORT)
    asyncio.create_task(periodic_disconnect(disconnect_interval))
    asyncio.create_task(client_loop())

    proc = psutil.Process(os.getpid())
    await monitor(proc, duration)

    # Hard exit - avoids cleanup hang in the reconnect sleep
    print("[main] exiting (hard exit to avoid cleanup hang)", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    p.add_argument("--msg-interval", type=float, default=DEFAULT_MSG_INTERVAL)
    p.add_argument("--disconnect-interval", type=float, default=DEFAULT_DISCONNECT_INTERVAL)
    args = p.parse_args()
    asyncio.run(main(args.duration, args.msg_interval, args.disconnect_interval))
