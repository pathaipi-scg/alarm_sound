from asyncua import Client

import asyncio

async def main():

    async with Client(
        "opc.tcp://172.28.231.251:49320"
    ) as client:

        node = client.get_node(
            "ns=2;s=LP2.SYSTEM.ALARM.RELOAD_ALARM"
        )

        await node.set_value(0)

        print("WRITE OK")

asyncio.run(main())