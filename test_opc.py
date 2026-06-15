import asyncio
from asyncua import Client

async def main():
    url = "opc.tcp://172.28.231.251:49320"

    print("connecting...", url)

    async with Client(url=url) as client:
        print("CONNECTED OK")

asyncio.run(main())