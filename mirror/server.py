"""Serves the mirror page and restyles the webcam frames it sends.

The browser owns the webcam (so this works from WSL, where USB cameras are
awkward), crops each frame to a 512x512 JPEG and sends it over a WebSocket.
Each frame is decoded on the GPU, restyled, encoded on the GPU and sent back.

    uv run python mirror/server.py            # then open http://localhost:8765
"""

import argparse
import asyncio
import json
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import torch
import torch.nn.functional as F
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from torchvision.io import ImageReadMode, decode_jpeg, encode_jpeg

from engine import Mirror

STATIC = pathlib.Path(__file__).parent / "static"
STYLES = json.loads((STATIC / "styles.json").read_text())

# Every piece of GPU work runs on this one thread: CUDA graphs belong to the
# thread that recorded them, and one queue also keeps frames from fighting.
gpu = ThreadPoolExecutor(max_workers=1)
mirror: Mirror | None = None


def load(compile):
    global mirror
    t0 = time.perf_counter()
    mirror = Mirror(compile=compile)
    print("warming up" + (" (first compile takes a few minutes)" if compile else ""), flush=True)
    frame = torch.zeros((3, mirror.size, mirror.size), dtype=torch.uint8, device="cuda")
    for _ in range(3):
        mirror(frame, STYLES[0]["prompt"], STYLES[0]["strength"])
    for style in STYLES:  # encode every preset prompt now, not mid-show
        mirror.embed(style["prompt"])
    torch.cuda.synchronize()
    print(f"ready in {time.perf_counter() - t0:.0f}s", flush=True)


def restyle(jpeg, prompt, strength):
    frame = decode_jpeg(torch.frombuffer(bytearray(jpeg), dtype=torch.uint8),
                        mode=ImageReadMode.RGB, device="cuda")
    if frame.shape[1:] != (mirror.size, mirror.size):
        frame = F.interpolate(frame[None].float(), size=(mirror.size, mirror.size),
                              mode="bilinear", antialias=True)[0].round().clamp(0, 255).to(torch.uint8)
    out = mirror(frame, prompt, strength)
    return encode_jpeg(out, quality=88).cpu().numpy().tobytes()


def create_app(compile):
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.get_running_loop().run_in_executor(gpu, load, compile)
        yield

    app = FastAPI(lifespan=lifespan)

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        loop = asyncio.get_running_loop()
        prompt, strength = STYLES[0]["prompt"], STYLES[0]["strength"]
        try:
            while True:
                msg = await socket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text"):
                    settings = json.loads(msg["text"])
                    prompt = str(settings.get("prompt", prompt))[:300]
                    strength = float(settings.get("strength", strength))
                elif msg.get("bytes"):
                    out = await loop.run_in_executor(gpu, restyle, msg["bytes"], prompt, strength)
                    await socket.send_bytes(out)
        except (WebSocketDisconnect, RuntimeError):
            pass

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-compile", action="store_true", help="start fast, run at half speed")
    args = parser.parse_args()
    uvicorn.run(create_app(compile=not args.no_compile), host=args.host, port=args.port, log_level="warning")
