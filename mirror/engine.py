"""The mirror's image engine: one webcam frame in, one restyled frame out.

This is img2img with a single denoising step, written out by hand so every
step is visible (and explainable at the stand):

  1. encode the frame into latent space with TAESD (a tiny, fast VAE)
  2. add a fixed amount of noise -- "strength" decides how much of the
     original survives
  3. ask the sd-turbo UNet once what that noise was, guided by the prompt
  4. subtract it to get a clean latent, and decode it back to pixels

sd-turbo is distilled to produce a finished image in one step, which is what
makes video rates possible on a laptop GPU. The noise is drawn once and
reused for every frame, so a still scene gives a still image instead of
flickering.
"""

import time

import torch
from diffusers import AutoencoderTiny, EulerDiscreteScheduler, UNet2DConditionModel
from transformers import CLIPTextModel, CLIPTokenizer

MODEL = "stabilityai/sd-turbo"
VAE = "madebyollin/taesd"


class Mirror:
    def __init__(self, size=512, device="cuda", compile=False, seed=0):
        self.size, self.device = size, device
        dtype = self.dtype = torch.float16

        self.tokenizer = CLIPTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained(
            MODEL, subfolder="text_encoder", variant="fp16", torch_dtype=dtype
        ).to(device)
        self.unet = UNet2DConditionModel.from_pretrained(
            MODEL, subfolder="unet", variant="fp16", torch_dtype=dtype
        ).to(device, memory_format=torch.channels_last)
        self.vae = AutoencoderTiny.from_pretrained(VAE, torch_dtype=dtype).to(device)

        sched = EulerDiscreteScheduler.from_pretrained(MODEL, subfolder="scheduler")
        self.alphas_cumprod = sched.alphas_cumprod.to(device)

        g = torch.Generator(device).manual_seed(seed)
        self.noise = torch.randn((1, 4, size // 8, size // 8), generator=g, device=device, dtype=dtype)
        self._embeds = {}

        # Uncompiled, the GPU sits idle about half the time waiting for Python
        # to launch the next kernel. Compiling the whole step with CUDA graphs
        # records it once and replays it as a single launch.
        self._step = torch.compile(self._step, mode="max-autotune") if compile else self._step

    @torch.inference_mode()
    def embed(self, prompt):
        if prompt not in self._embeds:
            ids = self.tokenizer(
                prompt, padding="max_length", max_length=self.tokenizer.model_max_length,
                truncation=True, return_tensors="pt",
            ).input_ids.to(self.device)
            self._embeds[prompt] = self.text_encoder(ids)[0]
            if len(self._embeds) > 64:
                self._embeds.pop(next(iter(self._embeds)))
        return self._embeds[prompt]

    @torch.inference_mode()
    def __call__(self, frame, prompt, strength=0.5):
        """frame: uint8 tensor (3, size, size) on the GPU. Returns the same shape."""
        t = int(min(max(strength, 0.05), 1.0) * 1000) - 1
        t = torch.tensor(t, device=self.device)  # a tensor, so changing it doesn't recompile
        return self._step(frame, self.embed(prompt), t).clone()

    def _step(self, frame, embeds, t):
        x = frame[None].to(self.dtype).div(127.5).sub(1)
        latent = self.vae.encode(x).latents

        a = self.alphas_cumprod[t].to(self.dtype)
        noisy = a.sqrt() * latent + (1 - a).sqrt() * self.noise

        eps = self.unet(
            noisy.contiguous(memory_format=torch.channels_last),
            t, encoder_hidden_states=embeds,
        ).sample
        clean = (noisy - (1 - a).sqrt() * eps) / a.sqrt()

        out = self.vae.decode(clean).sample[0]
        return out.clamp(-1, 1).add(1).mul(127.5).round().to(torch.uint8)


def benchmark(compile=False, n=60):
    m = Mirror(compile=compile)
    frame = torch.randint(0, 256, (3, 512, 512), dtype=torch.uint8, device="cuda")
    for _ in range(5):
        m(frame, "an oil painting")
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        m(frame, "an oil painting")
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / n
    print(f"compile={compile}: {dt * 1000:.1f} ms/frame = {1 / dt:.1f} fps, "
          f"peak VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GB")


if __name__ == "__main__":
    import sys
    benchmark(compile="--compile" in sys.argv)
