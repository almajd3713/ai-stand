# Invisibility Cloak

A live person detector (YOLOv8n) watches the camera and draws a red box around everyone it sees. Visitors hold up a printed **adversarial patch**, a picture trained to confuse this exact detector, and try to make the box disappear.

## Run it

```bash
uv run python cloak/server.py        # then open http://localhost:8768
```

It runs on an ordinary laptop CPU. The first start downloads YOLOv8n (6 MB) into `cloak/models/`.

| Key | Mode |
|---|---|
| `1` | **Real world.** The camera as it is. Hold the printed patch flat on your chest. |
| `2` | **Digital cloak.** The computer pastes the patch onto every detected person, then runs the detector again. This shows the effect cleanly, without printing or lighting problems. |
| `3` | **Control.** The same, with the *shuffled* patch: the same pixels in random order. If this still hid people, the trick would just be "cover your body". It doesn't. |

`↑` `↓` move the detection threshold (25% by default, YOLO's standard). Faint dashed boxes show detections below the threshold, so you can see the AI half-suspecting someone is there.

## Printing the patch

[`patches/patch.png`](patches/patch.png) is the trained patch, and [`patches/control.png`](patches/control.png) is its shuffled control.

- Print it **large**: at least A4, ideally A3, filling the page, in colour, on **matte** paper. Gloss reflects the lights and wipes out the pattern.
- Glue it to cardboard so it stays flat.
- Hold it on your chest, facing the camera, 1.5–3 m away, in even light.
- Print the control the same way, for the comparison.

## Training your own

```bash
uv run python cloak/train_patch.py                    # ~5 minutes on an RTX 4070 Laptop
uv run python cloak/train_patch.py --extra photos/    # add your own photos of people
```

Training downloads the Penn-Fudan pedestrian dataset (170 photos) into `cloak/data/`. It then optimizes the patch's pixels against the frozen detector. At the end it prints the share of people the detector still finds on 30 held-out photos with no patch, a grey square, the shuffled control, and the trained patch.

**The patch works best when trained on photos that look like the stand.** Take 50–100 photos of club members at the venue (upper body, the real lighting, the real background), put them in a folder, and train with `--extra`. That is the single biggest improvement for the real-world mode.

## Honest expectations

Physical adversarial patches are real and published ([Thys et al., 2019](https://arxiv.org/abs/1904.08653)), but they are fragile. Distance, angle, lighting and print quality all matter. Expect the printed patch to *lower* the detector's confidence reliably and to make the box vanish some of the time, not every time. That's part of the lesson. The digital mode shows the full effect.
