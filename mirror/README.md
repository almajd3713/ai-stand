# AI Mirror

A webcam mirror that repaints you in real time. Each frame goes through Stable Diffusion (`sd-turbo`, one denoising step) at roughly 19 frames per second on an RTX 4070 Laptop GPU.

## Run it

```bash
uv run python mirror/server.py
```

Then open **http://localhost:8765** in Chrome or Edge and allow the camera. In WSL, open it from the Windows browser: `localhost` is forwarded, and the browser handles the webcam, so WSL never has to touch USB.

The first start compiles the model, which takes a few minutes and briefly maxes out every CPU core. Later starts reuse the compile cache and are much quicker. To skip compiling while you test something, use `--no-compile` (about half the frame rate).

Before opening the page, check the server on its own:

```bash
uv run python mirror/selftest.py some_photo.jpg --save out.jpg
```

## Controls

| Key | Does |
|---|---|
| `e` | Open the **Style Studio** (below) |
| `/` | Open the studio with the prompt box selected, ready to type |
| `←` `→` or `1`–`9` | Change style |
| `↑` `↓` | More / less noise (less of you, more AI) |
| `space` | Toggle attract mode (changes style every 20 s; pauses for a minute after anyone presses a key) |
| `z` `x` | Zoom the camera in / out |
| `c` | Next camera |
| `h` | Hide the side panels |
| `f` | Fullscreen |

### Style Studio

Press `e` to open a drawer where you can:

- **Type a prompt** and watch the mirror follow as you type.
- **Drag the noise slider.** Around 0.5 keeps the person recognisable. Above 0.65 the model starts replacing them.
- **Save changes** to the selected style, **save it as a new style**, or **delete** it. Saved styles show up as buttons along the bottom.
- **Re-roll the noise:** same prompt, a different random take on it.
- **Reset** everything back to the built-in styles.

The built-in styles are in [`static/styles.json`](static/styles.json). Studio edits go to `mirror/styles.local.json`, which is kept out of git and takes over from the built-in list once it exists.

Prompts containing words from the small blocklist in [`server.py`](server.py) (`BLOCKED`) are ignored, and the studio tells you so. Extend the list for your audience. It catches the obvious stuff, not everything, so a club member should stay with the keyboard.

## How it works

[`engine.py`](engine.py) is a hand-written single-step img2img, short enough to walk someone through at the stand:

1. **Encode:** TAESD (a tiny VAE) compresses the 512×512 frame into a 64×64×4 latent.
2. **Noise:** mix in Gaussian noise at timestep `t = strength × 1000`. The *same* noise is reused every frame, so a still scene gives a still picture instead of flicker.
3. **Denoise:** the sd-turbo UNet predicts the noise, conditioned on the prompt. sd-turbo was distilled to do this in one step.
4. **Decode:** subtract the predicted noise and decode back to pixels.

The whole step is compiled with `torch.compile` using CUDA graphs. Uncompiled, the GPU sits idle half the time waiting for Python to launch kernels. Compiled, it runs as one replayed graph, which roughly doubles the frame rate. JPEG decoding and encoding also run on the GPU.

## On the day

- Laptop **plugged in**, Windows power mode on **Best performance**, and raised so air can get underneath.
- Close everything else that uses the GPU. The mirror wants it all to itself.
- An external webcam pointed at the crowd and a TV over HDMI work much better than the laptop screen.
- sd-turbo is under the Stability AI Community License, which is fine for a non-commercial club stand.
