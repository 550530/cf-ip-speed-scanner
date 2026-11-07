# -*- coding: utf-8 -*-
"""扫描 / 测速核心引擎（纯标准库 asyncio + socket + ssl，无第三方依赖）。

性能与修复要点：
1. 扫描分两阶段：先高并发 TCP 快筛存活（决定进度 PPS），再并发 trace 补机房标注，
   trace 不再阻塞存活计数。
2. trace 使用 Host/SNI = www.cloudflare.com，先 80 明文、失败回退 443 HTTPS（带 SNI）；
   失败回退 CIDR 地区标签，不丢弃 IP。
3. 所有连接在 finally 中显式关闭，避免句柄堆积拖慢并发。
4. 下载测速使用整体时间预算 + 大块读取，降低 read 次数与等待。
"""
import asyncio
import ipaddress
import random
import ssl
import time

from data import IP_POOLS, REGION_INFO, CF_COLO_MAP

TRACE_HOST = "www.cloudflare.com"
DOWNLOAD_HOST = "speed.cloudflare.com"


# ---------------------------------------------------------------- 候选生成
def gen_items(pool_name, ver, target=4888, per_subnet_v4=5, per_subnet_v6=200):
    """按 IP 池生成候选清单：[{'ip':..., 'region_hint':...}, ...]"""
    pool = IP_POOLS.get(pool_name, IP_POOLS["Cloudflare (官方全量 - 慢但全)"])
    subnets = pool.get(ver, [])
    items = []
    for cidr, hint in subnets:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if ver == "v4":
            subs = list(net.subnets(new_prefix=24))
            random.shuffle(subs)
            for s in subs[:150]:
                hosts = list(s.hosts()) or [s.network_address]
                random.shuffle(hosts)
                for h in hosts[:per_subnet_v4]:
                    items.append({"ip": str(h), "region_hint": hint})
        else:
            lo, hi = int(net.network_address), int(net.broadcast_address)
            for _ in range(per_subnet_v6):
                ip_int = random.randint(lo, hi)
                items.append({"ip": str(ipaddress.IPv6Address(ip_int)), "region_hint": hint})
    random.shuffle(items)
    return items[:target]


# ---------------------------------------------------------------- TCP 延迟
async def test_tcp(ip, port, timeout=1.0):
    """返回毫秒延迟；失败/超时返回 None。"""
    st = time.monotonic()
    w = None
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        return round((time.monotonic() - st) * 1000, 2)
    except Exception:
        return None
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass


# ---------------------------------------------------------------- trace 探测
async def _trace_on(ip, port, use_ssl, timeout):
    """单端口 trace 探测，返回 colo 代码或 None。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    w = None
    try:
        kw = {"ssl": ctx, "server_hostname": TRACE_HOST} if use_ssl else {}
        r, w = await asyncio.wait_for(
            asyncio.open_connection(ip, port, **kw), timeout,
        )
        req = (
            f"GET /cdn-cgi/trace HTTP/1.1\r\nHost: {TRACE_HOST}\r\n"
            f"User-Agent: curl/7.88.1\r\nConnection: close\r\n\r\n"
        )
        w.write(req.encode())
        await w.drain()
        data = b""
        while True:
            chunk = await asyncio.wait_for(r.read(4096), timeout)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data and len(data) > 200:
                break
        head, _, body = data.partition(b"\r\n\r\n")
        if b" 200 " not in head.split(b"\r\n")[0]:
            return None
        for line in body.decode("latin1", "replace").splitlines():
            if line.startswith("colo="):
                return line.split("=", 1)[1].strip().upper()
        return None
    except Exception:
        return None
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass


async def get_cf_trace(ip, timeout=1.2):
    """先 80 明文（更快），失败回退 443 HTTPS（带 SNI），返回 colo 或 None。"""
    for port, use_ssl in ((80, False), (443, True)):
        colo = await _trace_on(ip, port, use_ssl, timeout)
        if colo:
            return colo
    return None


# ---------------------------------------------------------------- 地区填充
def _region(iso):
    return REGION_INFO.get(iso, REGION_INFO["XX"])


def _fill_region(r, colo):
    hint = r.get("region_hint", "XX")
    if colo and colo in CF_COLO_MAP:
        iso, city = CF_COLO_MAP[colo]
        city_str = f"{city} ({colo})"
    elif colo:
        iso = "XX"
        city_str = f"未知节点 ({colo})"
    else:
        iso = hint
        city_str = _region(hint)[0] if hint in REGION_INFO else "未知节点"
    name, flag = _region(iso)
    r["iso"] = iso
    r["country_name"] = name
    r["flag"] = flag
    r["city"] = city_str
    r["colo"] = colo or ""
    return r


# ---------------------------------------------------------------- 阶段 1：TCP 快筛
async def scan_tcp(items, port, running, on_progress, max_workers=300,
                   latency_limit=600.0):
    """TCP 高并发快筛存活；每条先用 CIDR hint 填好基础地区字段，可直接回填界面。"""
    res = []
    total = len(items)
    done = 0
    st = time.monotonic()
    sem = asyncio.Semaphore(max_workers)

    async def probe(it):
        nonlocal done
        async with sem:
            if not running["on"]:
                return None
            lat = await test_tcp(it["ip"], port, timeout=1.0)
            done += 1
            on_progress(done, total, len(res), time.monotonic() - st)
            if lat is None or lat > latency_limit:
                return None
            r = {
                "ip": it["ip"],
                "port": port,
                "latency": lat,
                "region_hint": it.get("region_hint", "XX"),
                "speed": -1,
            }
            _fill_region(r, "")
            return r

    tasks = [asyncio.create_task(probe(it)) for it in items]
    for fut in asyncio.as_completed(tasks):
        r = await fut
        if r is not None:
            res.append(r)
    return res


# ---------------------------------------------------------------- 阶段 2：trace 补标注
async def annotate_all(res, running, on_one, max_workers=300,
                       timeout=1.2, budget=12.0):
    """并发 trace 补机房标注；每完成一条回调 on_one(r)。带整体时间预算，
    预算耗尽后剩余条目保留 hint 标注，不再长尾等待。"""
    if not res:
        return
    sem = asyncio.Semaphore(max_workers)
    st = time.monotonic()

    async def annotate(r):
        async with sem:
            if not running["on"]:
                return
            if time.monotonic() - st > budget:
                return
            colo = await get_cf_trace(r["ip"], timeout=timeout)
            if running["on"]:
                _fill_region(r, colo)
                on_one(r)

    await asyncio.gather(*[annotate(r) for r in res], return_exceptions=True)


# ---------------------------------------------------------------- 兼容封装
async def batch_test(items, port, running, on_progress, max_workers=300,
                     trace=True, latency_limit=600.0):
    res = await scan_tcp(items, port, running, on_progress, max_workers, latency_limit)
    if trace and res and running["on"]:
        await annotate_all(res, running, lambda r: None, max_workers)
    return res


# ---------------------------------------------------------------- 下载测速
async def download_speed(ip, port, running, bytes_total=3_000_000,
                         connect_timeout=4.0, read_budget=5.0, min_bytes=200_000):
    if not running["on"]:
        return -1.0
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    w = None
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(ip, port, ssl=ctx, server_hostname=DOWNLOAD_HOST),
            connect_timeout,
        )
        req = (
            f"GET /__down?bytes={bytes_total} HTTP/1.1\r\nHost: {DOWNLOAD_HOST}\r\n"
            f"User-Agent: curl/7.68.0\r\nConnection: close\r\n\r\n"
        )
        w.write(req.encode())
        await w.drain()

        header_done = False
        length = 0
        st = time.monotonic()
        deadline = st + read_budget
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            try:
                chunk = await asyncio.wait_for(r.read(65536), remain)
            except asyncio.TimeoutError:
                break  # 读超时保留已读字节，按样本估算速度
            if not chunk:
                break
            if not header_done:
                _head, sep, body = chunk.partition(b"\r\n\r\n")
                if sep:
                    header_done = True
                    length += len(body)
                continue
            length += len(chunk)
            if length >= bytes_total:
                break

        dur = time.monotonic() - st
        if dur <= 0.1 or length < min_bytes:
            return -1.0
        return round((length / 1024 / 1024) / dur, 2)
    except Exception:
        return -1.0
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass


# ---------------------------------------------------------------- CLI 自测
if __name__ == "__main__":
    import sys

    running = {"on": True}
    pool = sys.argv[1] if len(sys.argv) > 1 else "Cloudflare (官方全量 - 慢但全)"
    ver = sys.argv[2] if len(sys.argv) > 2 else "v4"
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    def on_done(c, t, alive, elapsed):
        print(f"\r进度 {c}/{t} 存活 {alive} {elapsed:.1f}s", end="")

    items = gen_items(pool, ver, target)
    print(f"候选 {len(items)} 个，池={pool} {ver}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results = loop.run_until_complete(batch_test(items, 443, running, on_done, trace=True))
    loop.close()
    results.sort(key=lambda x: x["latency"])
    print(f"\n存活 {len(results)} / {len(items)}")
    for r in results[:20]:
        print(f"{r['flag']} {r['ip']:22} {r['latency']:7.2f}ms {r['city']}")
