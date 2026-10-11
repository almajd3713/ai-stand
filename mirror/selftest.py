"""Check a running mirror server without a webcam: sends an image as fast as
the page would (two frames in flight) and reports the frame rate.

    uv run python mirror/selftest.py [photo.jpg] [--seconds 10] [--save out.jpg]
"""

import argparse
import asyncio
import io
import json
import time

import websockets
from PIL import Image, ImageOps


async def main(args):
    if args.image:
        img = ImageOps.fit(Image.open(args.image).convert("RGB"), (512, 512))
    else:
        img = Image.radial_gradient("L").convert("RGB").resize((512, 512))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    frame = buf.getvalue()

    styles = json.load(open(__file__.replace("selftest.py", "static/styles.json")))
    async with websockets.connect(f"ws://localhost:{args.port}/ws", max_size=None) as ws:
        await ws.send(json.dumps({"prompt": styles[0]["prompt"], "strength": styles[0]["strength"]}))
        for _ in range(2):
            await ws.send(frame)
        received, last, t0 = 0, None, time.perf_counter()
        while time.perf_counter() - t0 < args.seconds:
            last = await ws.recv()
            received += 1
            await ws.send(frame)
        elapsed = time.perf_counter() - t0
    print(f"{received / elapsed:.1f} frames/s over {elapsed:.0f}s ({styles[0]['name']})")
    if args.save and last:
        open(args.save, "wb").write(last)
        print("saved", args.save)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("image", nargs="?")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--save")
    asyncio.run(main(p.parse_args()))
