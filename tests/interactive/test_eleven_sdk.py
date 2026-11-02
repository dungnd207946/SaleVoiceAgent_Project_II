import asyncio
import os

import websockets
from dotenv import load_dotenv

load_dotenv("/Users/nmcxyz/Desktop/MyFolder/NobleX/voiceagentrag/.env")
api_key = os.getenv("ELEVENLABS_API_KEY")
voice_id = os.getenv("ELEVENLABS_TTS_VOICE_ID")


async def test_ws(model_id):
    url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={model_id}&output_format=pcm_24000"
    )
    try:
        ws = await websockets.connect(url, additional_headers={"xi-api-key": api_key})
        await ws.close()
        print(f"[WS] Model {model_id}: SUCCESS")
    except Exception as e:
        print(f"[WS] Model {model_id}: ERROR {e}")


async def main():
    print("Testing Raw WebSocket...")
    await test_ws("eleven_v3")
    await test_ws("eleven_multilingual_v2")
    await test_ws("eleven_multilingual_v3")
    await test_ws("eleven_flash_v2_5")

    print("\nTesting Official SDK...")
    try:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=api_key)
        for model in ["eleven_v3", "eleven_multilingual_v3"]:
            try:
                list(
                    client.text_to_speech.convert_as_stream(
                        text="Hello", voice_id=voice_id, model_id=model, output_format="pcm_24000"
                    )
                )
                print(f"[SDK HTTP Stream] Model {model}: SUCCESS")
            except Exception as e:
                print(f"[SDK HTTP Stream] Model {model}: ERROR {e}")
    except Exception as e:
        print(f"[SDK] Setup error: {e}")


asyncio.run(main())
