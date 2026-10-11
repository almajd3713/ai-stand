"""Invisibility Cloak: a live person detector you can hide from with a printed patch.

    uv run python cloak/server.py         # then open http://localhost:8768

Runs on a plain laptop CPU (YOLOv8n is small). Train the patch first with
train_patch.py, or use the one committed in patches/.

Modes:
  real     the detector sees the camera as it is: hold up the printed patch
  digital  the patch is pasted onto everyone's chest in software, then detected again
  control  same, with the shuffled control patch: same colours, no pattern
"""

import argparse
import asyncio
import io
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from PIL import Image
from ultralytics import YOLO

HERE = pathlib.Path(__file__).parent
PERSON = 0
FLOOR = 0.05          # report anything above this, so the page can show near-misses
PATCH_FOR = {"digital": "patch", "control": "control"}

detector = None
patches = {}
worker = ThreadPoolExecutor(max_workers=1)


def load():
    global detector
    detector = YOLO(str(HERE / "models" / "yolov8n.pt"))
    for name in ("patch", "control"):
        path = HERE / "patches" / f"{name}.png"
        if path.exists():
            patches[name] = Image.open(path).convert("RGB")
    detector.predict(np.zeros((480, 640, 3), np.uint8), verbose=False)  # warm up
    print(f"detector on {detector.device}; patches: {', '.join(patches) or 'none yet'}", flush=True)


def detect(img):
    r = detector.predict(img, classes=[PERSON], conf=FLOOR, verbose=False)[0]
    return [[*map(round, b.tolist()), round(float(s), 3)] for b, s in zip(r.boxes.xyxy.cpu(), r.boxes.conf.cpu())]


def paste(img, boxes, patch):
    """The digital cloak: the patch on each person's chest, sized like in training."""
    img = img.copy()
    for x1, y1, x2, y2, _ in boxes:
        w, h = x2 - x1, y2 - y1
        side = int(max(12, min(0.35 * (w * h) ** 0.5, w * 0.95)))
        cx, cy = (x1 + x2) / 2, y1 + 0.44 * h
        img.paste(patch.resize((side, side), Image.BILINEAR), (int(cx - side / 2), int(cy - side / 2)))
    return img


def process(jpeg, mode):
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    boxes = detect(img)
    if PATCH_FOR.get(mode) in patches:
        cloaked = paste(img, [b for b in boxes if b[4] >= 0.25], patches[PATCH_FOR[mode]])
        buf = io.BytesIO()
        cloaked.save(buf, "JPEG", quality=85)
        return detect(cloaked), buf.getvalue()
    return boxes, None


@asynccontextmanager
async def lifespan(app):
    await asyncio.get_running_loop().run_in_executor(worker, load)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/info")
def info():
    return {"patches": sorted(patches), "device": str(detector.device) if detector else None}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    loop = asyncio.get_running_loop()
    mode = "real"
    try:
        while True:
            msg = await socket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                mode = json.loads(msg["text"]).get("mode", mode)
            elif msg.get("bytes"):
                boxes, image = await loop.run_in_executor(worker, process, msg["bytes"], mode)
                await socket.send_text(json.dumps({"boxes": boxes, "image": image is not None}))
                if image is not None:
                    await socket.send_bytes(image)
    except (WebSocketDisconnect, RuntimeError):
        pass


app.mount("/patches", StaticFiles(directory=HERE / "patches"), name="patches")
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--cpu", action="store_true", help="force the CPU even if a GPU is there")
    args = parser.parse_args()
    if args.cpu:
        torch.cuda.is_available = lambda: False
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
