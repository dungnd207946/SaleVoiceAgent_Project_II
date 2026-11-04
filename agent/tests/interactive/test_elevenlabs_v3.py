import asyncio
import json
import os

import websockets
from dotenv import load_dotenv

load_dotenv("/Users/nmcxyz/Desktop/MyFolder/NobleX/voiceagentrag/.env")
api_key = os.getenv("ELEVENLABS_API_KEY")
voice_id = "pNInz6obpgDQGcFmaJgB"  # Adam


async def test_ws(model_id, use_lang_code=True):
    url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={model_id}&output_format=pcm_24000"
    )
    if use_lang_code:
        url += "&language_code=vi"

    label = f"{model_id} (lang_code={'vi' if use_lang_code else 'NONE'})"
    try:
        ws = await websockets.connect(url, additional_headers={"xi-api-key": api_key})
        await ws.send(
            json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}})
        )

        # Give it a tiny moment to see if it closes with 1008
        await asyncio.sleep(0.5)
        # Send some text
        await ws.send(json.dumps({"text": "Hello world", "try_trigger_generation": True}))

        # Read response
        try:
            async for raw in ws:
                data = json.loads(raw)
                if data.get("audio"):
                    print(f"[SUCCESS] {label} received audio!")
                    break
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[ERROR Closed] {label} - {e.code} {e.reason}")

        await ws.close()
    except Exception as e:
        print(f"[ERROR Connect] {label} - {e}")


async def main():
    await test_ws("eleven_v3", use_lang_code=True)
    await test_ws("eleven_v3", use_lang_code=False)

    await test_ws("eleven_flash_v2_5", use_lang_code=True)
    await test_ws("eleven_flash_v2_5", use_lang_code=False)


asyncio.run(main())
