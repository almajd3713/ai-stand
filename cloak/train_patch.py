"""Train an adversarial patch that makes YOLOv8n stop seeing people.

    uv run python cloak/train_patch.py                  # ~20 minutes on an RTX 4070 Laptop
    uv run python cloak/train_patch.py --extra my_frames/   # also train on your own photos

The patch is just a 300x300 image. Training pastes it onto every person in a set
of photos, runs the detector, and nudges the patch's pixels (by gradient
descent, like training a network, except the network stays frozen and the
*image* is what learns) so that the detector's highest "person" score drops.

To survive printing and a webcam, every paste is randomly rotated, scaled,
brightened, darkened and noised (expectation over transformation), and the
patch is kept smooth (total variation) so a printer can reproduce it.

Based on Thys, Van Ranst & Goedemé, "Fooling automated surveillance cameras:
adversarial patches to attack person detection" (CVPR Workshops 2019).
"""

import argparse
import io
import math
import pathlib
import random
import urllib.request
import zipfile

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from ultralytics import YOLO

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
MODEL = HERE / "models" / "yolov8n.pt"
PATCHES = HERE / "patches"
PENN_FUDAN = "https://www.cis.upenn.edu/~jshi/ped_html/PennFudanPed.zip"
SIZE = 640          # detector input size
PERSON = 0          # COCO class id


# ---------------------------------------------------------------- data

def load_detector():
    if not MODEL.exists():
        MODEL.parent.mkdir(exist_ok=True)
        YOLO("yolov8n.pt")  # downloads into the working directory
        pathlib.Path("yolov8n.pt").replace(MODEL)
    return YOLO(str(MODEL))


def ensure_dataset():
    root = DATA / "PennFudanPed"
    if not root.exists():
        print("downloading the Penn-Fudan pedestrian dataset (~50 MB)…", flush=True)
        DATA.mkdir(exist_ok=True)
        blob = urllib.request.urlopen(PENN_FUDAN, timeout=120).read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():  # refuse anything that would land outside data/
                if name.startswith("/") or ".." in pathlib.PurePosixPath(name).parts:
                    raise RuntimeError(f"unsafe path in archive: {name}")
            z.extractall(DATA)
    return root


def load_samples(root, extra=None, detector=None):
    """[(image as float tensor 3xHxW in 0..1, person boxes Nx4 xyxy)]"""
    samples = []
    for img_path in sorted((root / "PNGImages").glob("*.png")):
        mask = np.array(Image.open(root / "PedMasks" / img_path.name.replace(".png", "_mask.png")))
        boxes = []
        for i in np.unique(mask)[1:]:
            ys, xs = np.nonzero(mask == i)
            boxes.append([xs.min(), ys.min(), xs.max(), ys.max()])
        img = torch.from_numpy(np.array(Image.open(img_path).convert("RGB"))).permute(2, 0, 1).float() / 255
        samples.append((img, torch.tensor(boxes, dtype=torch.float32)))
    if extra:  # your own photos: boxes come from the detector itself
        for p in sorted(pathlib.Path(extra).glob("*")):
            if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            pil = Image.open(p).convert("RGB")
            r = detector.predict(pil, classes=[PERSON], conf=0.4, verbose=False)[0]
            if len(r.boxes):
                img = torch.from_numpy(np.array(pil)).permute(2, 0, 1).float() / 255
                samples.append((img, r.boxes.xyxy.cpu().float()))
        print(f"{len(samples)} images including your own", flush=True)
    return samples


def frame(img, boxes, close_up):
    """Crop (optionally to one person's upper body, like a webcam at a stand) and
    letterbox to SIZE x SIZE. Returns the image and the visible person boxes."""
    _, H, W = img.shape
    if close_up:
        x1, y1, x2, y2 = boxes[random.randrange(len(boxes))].tolist()
        w, h = x2 - x1, y2 - y1
        cx1, cy1 = max(0, x1 - random.uniform(0.2, 0.6) * w), max(0, y1 - random.uniform(0.05, 0.2) * h)
        cx2, cy2 = min(W, x2 + random.uniform(0.2, 0.6) * w), min(H, y1 + random.uniform(0.55, 0.8) * h)
    else:
        cx1, cy1, cx2, cy2 = 0, 0, W, H
    cx1, cy1, cx2, cy2 = int(cx1), int(cy1), int(cx2), int(cy2)
    crop = img[:, cy1:cy2, cx1:cx2]
    b = boxes.clone()
    b[:, [0, 2]] = (b[:, [0, 2]] - cx1).clamp(0, cx2 - cx1)
    b[:, [1, 3]] = (b[:, [1, 3]] - cy1).clamp(0, cy2 - cy1)
    b = b[((b[:, 2] - b[:, 0]) > 20) & ((b[:, 3] - b[:, 1]) > 40)]
    s = SIZE / max(crop.shape[1:])
    nh, nw = round(crop.shape[1] * s), round(crop.shape[2] * s)
    out = torch.full((3, SIZE, SIZE), 114 / 255, device=img.device)
    oy, ox = (SIZE - nh) // 2, (SIZE - nw) // 2
    out[:, oy:oy + nh, ox:ox + nw] = F.interpolate(crop[None], size=(nh, nw), mode="bilinear", antialias=True)[0]
    b = b * s + torch.tensor([ox, oy, ox, oy], device=b.device)
    return out.clamp(0, 1), b  # resizing can overshoot 1.0, and YOLO then assumes 0-255


# ---------------------------------------------------------------- the patch on a person

def transformed(patch, size, train):
    """The patch as a camera might see it: resized, rotated, lit differently, noisy.
    Returns the patch and a mask, both size x size."""
    p = patch
    if train:
        p = p * random.uniform(0.8, 1.2) + random.uniform(-0.12, 0.12)          # contrast, brightness
        p = p + torch.randn_like(p) * 0.03                                        # sensor noise
    p = F.interpolate(p[None], size=(size, size), mode="bilinear", align_corners=False)[0]
    mask = torch.ones_like(p[:1])
    if train:
        a = math.radians(random.uniform(-20, 20))
        theta = torch.tensor([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0]], device=p.device)
        grid = F.affine_grid(theta[None], (1, 3, size, size), align_corners=False)
        p = F.grid_sample(p[None], grid, align_corners=False)[0]
        mask = F.grid_sample(mask[None], grid, align_corners=False)[0]
    return p.clamp(0, 1), mask


def apply(img, boxes, patch, train=True, scale=None):
    """Paste the patch onto the chest of every person box."""
    img = img.clone()
    for x1, y1, x2, y2 in boxes.tolist():
        w, h = x2 - x1, y2 - y1
        side = int((scale or random.uniform(0.28, 0.42)) * math.sqrt(w * h))
        side = max(12, min(side, int(w * 0.95)))
        cx = (x1 + x2) / 2 + (random.uniform(-0.08, 0.08) * w if train else 0)
        cy = y1 + (random.uniform(0.38, 0.5) if train else 0.44) * h
        px, py = int(cx - side / 2), int(cy - side / 2)
        p, m = transformed(patch, side, train)
        ix1, iy1, ix2, iy2 = max(px, 0), max(py, 0), min(px + side, SIZE), min(py + side, SIZE)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        sp = p[:, iy1 - py:iy2 - py, ix1 - px:ix2 - px]
        sm = m[:, iy1 - py:iy2 - py, ix1 - px:ix2 - px]
        img[:, iy1:iy2, ix1:ix2] = img[:, iy1:iy2, ix1:ix2] * (1 - sm) + sp * sm
    return img


# ---------------------------------------------------------------- training

def person_scores(net, x):
    """The detector's 'person' confidence for each of its 8400 candidate boxes."""
    out = net(x)
    out = out[0] if isinstance(out, (list, tuple)) else out
    return out[:, 4 + PERSON, :]


def total_variation(p):
    return (p[:, 1:, :] - p[:, :-1, :]).abs().mean() + (p[:, :, 1:] - p[:, :, :-1]).abs().mean()


def recall(detector, samples, patch, device, scale=0.35, conf=0.25):
    """Share of real people the detector still finds (box IoU > 0.4) with this patch on them."""
    found = total = 0
    random.seed(1)
    for img, boxes in samples:
        x, b = frame(img, boxes, close_up=False)
        if len(b) == 0:
            continue
        if patch is not None:
            x = apply(x, b, patch.to(device), train=False, scale=scale)
        r = detector.predict(x[None], classes=[PERSON], conf=conf, verbose=False)[0]
        det = r.boxes.xyxy.cpu()
        for gt in b.cpu():
            total += 1
            if len(det):
                ix1, iy1 = torch.maximum(det[:, 0], gt[0]), torch.maximum(det[:, 1], gt[1])
                ix2, iy2 = torch.minimum(det[:, 2], gt[2]), torch.minimum(det[:, 3], gt[3])
                inter = (ix2 - ix1).clamp(0) * (iy2 - iy1).clamp(0)
                union = (det[:, 2] - det[:, 0]) * (det[:, 3] - det[:, 1]) + (gt[2] - gt[0]) * (gt[3] - gt[1]) - inter
                found += int((inter / union).max() > 0.4)
    return found / max(total, 1)


def main(args):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    random.seed(0)
    torch.manual_seed(0)
    detector = load_detector()
    net = detector.model.to(device).eval()
    for p in net.parameters():
        p.requires_grad_(False)

    samples = [(img.to(device), boxes.to(device))
               for img, boxes in load_samples(ensure_dataset(), args.extra, detector)]
    random.shuffle(samples)
    test, train = samples[:30], samples[30:]
    print(f"{len(train)} training images, {len(test)} held out", flush=True)

    if args.eval_only:
        evaluate(detector, test, load_png(PATCHES / "patch.png", device), load_png(PATCHES / "control.png", device), device)
        return

    patch = torch.full((3, 300, 300), 0.5, device=device).add_(torch.rand(3, 300, 300, device=device) * 0.2 - 0.1)
    patch.requires_grad_(True)
    opt = torch.optim.Adam([patch], lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps)

    PATCHES.mkdir(exist_ok=True)
    for step in range(1, args.steps + 1):
        batch = []
        for _ in range(args.batch):
            img, boxes = random.choice(train)
            x, b = frame(img, boxes, close_up=random.random() < 0.5)
            batch.append(apply(x, b, patch) if len(b) else x)
        scores = person_scores(net, torch.stack(batch))
        top = scores.topk(10, dim=1).values                  # the ten most confident "person" candidates
        det_loss = top[:, 0].mean() + 0.5 * top.mean()       # crush the best one, and the runners-up
        loss = det_loss + args.tv * total_variation(patch)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        with torch.no_grad():
            patch.clamp_(0, 1)
        if step % 100 == 0 or step == 1:
            print(f"step {step:5d}  top person score {det_loss.item():.3f}  smoothness {total_variation(patch).item():.4f}", flush=True)
        if step % 500 == 0:
            save(patch, PATCHES / "patch.png")

    save(patch, PATCHES / "patch.png")
    # A control: the same pixels, shuffled. Same colours and size, no structure.
    flat = patch.detach().reshape(3, -1)
    control = flat[:, torch.randperm(flat.shape[1], device=device)].reshape(patch.shape)
    save(control, PATCHES / "control.png")

    evaluate(detector, test, patch.detach(), control, device)


def evaluate(detector, test, patch, control, device):
    print("\nperson recall on 30 held-out photos (lower = more invisible):")
    print(f"  {'':18s} {'normal print':>13s} {'bigger print':>13s}")
    grey = torch.full_like(patch, 0.5)
    for name, p in [("no patch", None), ("grey square", grey), ("shuffled control", control), ("adversarial patch", patch)]:
        normal, big = (recall(detector, test, p, device, scale=k) for k in (0.35, 0.45))
        print(f"  {name:18s} {normal:13.0%} {big:13.0%}", flush=True)


def load_png(path, device):
    return torch.from_numpy(np.array(Image.open(path).convert("RGB"))).permute(2, 0, 1).float().div(255).to(device)


def save(patch, path):
    Image.fromarray((patch.detach().clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)).save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=0.03)
    ap.add_argument("--tv", type=float, default=1.0)
    ap.add_argument("--extra", help="folder of your own photos with people in them")
    ap.add_argument("--eval-only", action="store_true", help="just measure the saved patches")
    main(ap.parse_args())
