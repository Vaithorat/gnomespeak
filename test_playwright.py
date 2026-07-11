import asyncio, json, websockets

async def test():
    uri = 'ws://127.0.0.1:8765'
    async with websockets.connect(uri) as ws:
        # Test 1: YouTube play
        msg = {
            'type': 'command',
            'text': 'play golmaal 3 on youtube',
            'api_key': '',
            'provider': '',
            'session_id': 'test_pw_1'
        }
        print("=== TEST 1: play golmaal 3 ===")
        await ws.send(json.dumps(msg))
        resp = await asyncio.wait_for(ws.recv(), timeout=60)
        data = json.loads(resp)
        print(json.dumps(data, indent=2))

        # Test 2: Context test - follow up
        print("\n=== TEST 2: now pause it (context test) ===")
        msg2 = {
            'type': 'command',
            'text': 'now pause it',
            'api_key': '',
            'provider': '',
            'session_id': 'test_pw_1'
        }
        await ws.send(json.dumps(msg2))
        resp2 = await asyncio.wait_for(ws.recv(), timeout=60)
        data2 = json.loads(resp2)
        print(json.dumps(data2, indent=2))

asyncio.run(test())
