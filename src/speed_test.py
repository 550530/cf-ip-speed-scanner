# -*- coding: utf-8 -*-
import asyncio, sys
from core import download_speed

async def main():
    ips = ["104.20.12.96", "104.16.153.243", "162.159.61.231"]
    running = {"on": True}
    for ip in ips:
        sp = await download_speed(ip, 443, running)
        print(f"{ip}: {sp} MB/s")

asyncio.run(main())
