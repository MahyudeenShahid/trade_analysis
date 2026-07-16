import asyncio
import websockets
import json

async def main():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected successfully!")
            # Wait and listen for messages
            for i in range(5):
                msg = await websocket.recv()
                # Print a small snippet of the message
                print(f"Received message {i+1}: {msg[:200]}...")
            print("Finished successfully without unexpected disconnect.")
    except Exception as e:
        print(f"Error occurred: {type(e).__name__}: {e}")

asyncio.run(main())
