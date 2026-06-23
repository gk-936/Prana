"""
Conservative load test for PRANA backend on a Raspberry Pi 3B+.
Tests /health for latency/concurrency, then a single /risk/current call.
"""

import asyncio
import statistics
import time

import aiohttp

BASE_URL = "http://100.114.86.91:8000"

RISK_PAYLOAD = {
    "lat": 12.9716,
    "lon": 77.5946,
    "location_name": "Test Location",
    "urban_heat_offset": 3.0,
}


async def get_health(session):
    t0 = time.perf_counter()
    try:
        async with session.get(f"{BASE_URL}/health", timeout=aiohttp.ClientTimeout(total=10)) as r:
            return r.status, time.perf_counter() - t0
    except Exception as e:
        print(f"  ERROR: {e}")
        return 0, time.perf_counter() - t0


async def post_risk(session):
    t0 = time.perf_counter()
    try:
        async with session.post(
            f"{BASE_URL}/risk/current",
            json=RISK_PAYLOAD,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as r:
            return r.status, time.perf_counter() - t0
    except Exception as e:
        print(f"  ERROR: {e}")
        return 0, time.perf_counter() - t0


def summarise(label, results):
    latencies = [l for _, l in results]
    statuses = [s for s, _ in results]
    ok = statuses.count(200)
    print("")
    print("--------------------------------------------------")
    print(f"  {label}")
    print(f"  Requests : {len(results)}")
    print(f"  Success  : {ok}/{len(results)}")
    print(f"  Min      : {min(latencies)*1000:.0f} ms")
    print(f"  Avg      : {statistics.mean(latencies)*1000:.0f} ms")
    print(f"  Median   : {statistics.median(latencies)*1000:.0f} ms")
    print(f"  Max      : {max(latencies)*1000:.0f} ms")
    if len(latencies) > 1:
        print(f"  StdDev   : {statistics.stdev(latencies)*1000:.0f} ms")
    non_200 = [(s, f"{l*1000:.0f}ms") for s, l in results if s != 200]
    if non_200:
        print(f"  Non-200  : {non_200}")


async def run_concurrent_health(n, connector):
    async with aiohttp.ClientSession(connector=connector, connector_owner=False) as session:
        return await asyncio.gather(*[get_health(session) for _ in range(n)])


async def main():
    print(f"Target: {BASE_URL}")
    print("Pi 3B+ mode - gentle ramp, gaps between stages")

    connector = aiohttp.TCPConnector(limit=20)

    # Stage 1: single health ping
    async with aiohttp.ClientSession(connector=connector, connector_owner=False) as session:
        status, latency = await get_health(session)
    if status == 0:
        print("FAIL: Could not reach server. Check IP/port and that backend is running.")
        await connector.close()
        return
    print(f"\n[OK] Server reachable - /health responded {status} in {latency*1000:.0f} ms")

    # Stage 2: sequential baseline 10 requests
    print("\n[Stage 2] Sequential /health x10 ...")
    async with aiohttp.ClientSession(connector=connector, connector_owner=False) as session:
        results = [await get_health(session) for _ in range(10)]
    summarise("/health sequential x10", results)
    await asyncio.sleep(3)

    # Stage 3: concurrent ramp 2, 5, 10
    for n in [2, 5, 10]:
        print(f"\n[Stage 3] Concurrent /health x{n} ...")
        results = await run_concurrent_health(n, connector)
        summarise(f"/health concurrent x{n}", results)
        await asyncio.sleep(5)

    # Stage 4: single /risk/current
    print("\n[Stage 4] Single /risk/current (may take 10-30s on Pi) ...")
    async with aiohttp.ClientSession(connector=connector, connector_owner=False) as session:
        status, latency = await post_risk(session)
    print(f"  Status: {status}  |  Time: {latency:.2f} s")
    if status == 200:
        print("  [OK] Risk endpoint functional")
    elif status == 429:
        print("  [!] Rate-limited - server is protecting itself correctly")
    else:
        print(f"  [!] Unexpected status {status}")

    await connector.close()
    print("\n--------------------------------------------------")
    print("Done. Review results above before increasing load.")


if __name__ == "__main__":
    asyncio.run(main())
