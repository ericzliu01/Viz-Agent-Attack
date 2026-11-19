"""Independent CoTTA implementation, arXiv:2603.29418v2, equations 5–14.

No victim queries are used in optimization. All tensors use RGB in [0, 1];
configuration budgets/steps use the paper's 8-bit pixel units. The TOTAL
trigger + noise is projected around the ORIGINAL image, including at export.
See docs/cotta.md for reproduction choices not specified in the paper.
"""
from dataclasses import asdict, dataclass
import math
import random
import textwrap

import numpy as np
from PIL import Image, ImageDraw
import torch
import torch.nn.functional as F

from qa_attacks.image_channels import load_font


DEFAULT_SURROGATES = (
    "openai/clip-vit-base-patch16",
    "openai/clip-vit-base-patch32",
    "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
)
VARIANTS = ("cotta", "trigger_only", "no_trigger", "static_target", "no_local")


@dataclass(frozen=True)
class CottaConfig:
    steps: int = 300
    epsilon: float = 16.0
    source_step: float = 1.0
    target_step: float = 1.0
    pull: float = 1.0
    push: float = 0.5
    geometry_lr: float = 0.01
    seed: int = 0
    variant: str = "cotta"
    font_size: int = 48
    wrap_chars: int = 36

    def __post_init__(self):
        if self.steps < 1 or not 0 <= self.epsilon <= 255:
            raise ValueError("steps must be positive; epsilon must be in [0, 255]")
        if any(not math.isfinite(v) or v < 0 for v in (
                self.source_step, self.target_step, self.pull, self.push, self.geometry_lr)):
            raise ValueError("step sizes, weights, and learning rate must be finite and nonnegative")
        if self.variant not in VARIANTS or self.font_size < 1 or self.wrap_chars < 1:
            raise ValueError("invalid variant or text rendering dimensions")


def choose_device(name="auto"):
    if name != "auto":
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class ClipSurrogate:
    """Frozen HF CLIP with differentiable, full-image resizing (no center crop)."""

    def __init__(self, model_id, device="cpu"):
        from transformers import AutoTokenizer, CLIPModel, CLIPImageProcessor
        self.device = torch.device(device)
        # Original OpenAI repos ship .bin weights. Avoid Transformers' optional
        # background conversion/download of a second full checkpoint. PyTorch
        # >=2.6 loads these with weights_only=True through Transformers.
        loading = {"use_safetensors": False} if model_id.startswith("openai/clip-") else {}
        self.model = CLIPModel.from_pretrained(model_id, attn_implementation="eager", **loading)
        self.model = self.model.to(self.device).eval().requires_grad_(False)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        processor = CLIPImageProcessor.from_pretrained(model_id)
        self.size = self.model.config.vision_config.image_size
        self.mean = torch.tensor(processor.image_mean, device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor(processor.image_std, device=self.device).view(1, 3, 1, 1)
        self.metadata = {"model": model_id, "revision": self.model.config._commit_hash,
                         "image_size": self.size, "preprocess": "bilinear_full_image_no_crop"}

    def image_features(self, image):
        resized = F.interpolate(image, (self.size, self.size), mode="bilinear", align_corners=False)
        out = self.model.vision_model(pixel_values=(resized - self.mean) / self.std)
        global_features = self.model.visual_projection(out.pooler_output)
        patches = self.model.vision_model.post_layernorm(out.last_hidden_state[:, 1:])
        local_features = self.model.visual_projection(patches)
        return global_features, local_features

    @torch.no_grad()
    def text_features(self, texts):
        # Do not silently truncate the desired answer from long instructions.
        tokens = self.tokenizer(texts, padding=True, return_tensors="pt", truncation=False)
        if tokens.input_ids.shape[1] > self.model.config.text_config.max_position_embeddings:
            raise ValueError("Target text exceeds CLIP's context window; shorten the target")
        out = self.model.text_model(**{k: v.to(self.device) for k, v in tokens.items()})
        return self.model.text_projection(out.pooler_output)


def text_bitmap(text, font_size=48, wrap_chars=36):
    """Tightly cropped white glyphs on black; no image-generation service."""
    if not text.strip():
        raise ValueError("target text must not be empty")
    font = load_font(font_size)
    lines = "\n".join(textwrap.wrap(text, width=wrap_chars))
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = draw.multiline_textbbox((0, 0), lines, font=font, spacing=4)
    canvas = Image.new("L", (max(1, box[2] - box[0]), max(1, box[3] - box[1])))
    ImageDraw.Draw(canvas).multiline_text((-box[0], -box[1]), lines, font=font, fill=255, spacing=4)
    return torch.from_numpy(np.array(canvas, dtype=np.float32) / 255)[None, None]


def transformed_mask(bitmap, height, width, scale, angle):
    """Centered inverse affine map, Eqs. 5–6, with straight-through binarization.

    Pixel-aspect correction makes angle a physical rotation on nonsquare images.
    Bilinear gradients update geometry; the forward trigger is binary.
    """
    rh = (bitmap.shape[-2] / height * scale).clamp(0.05, 0.95)
    rw = (bitmap.shape[-1] / width * scale).clamp(0.05, 0.95)
    c, s, z = angle.cos(), angle.sin(), scale * 0
    matrix = torch.stack((c / rw, s * height / width / rw, z,
                          -s * width / height / rh, c / rh, z)).reshape(1, 2, 3)
    grid = F.affine_grid(matrix, (1, 1, height, width), align_corners=False)
    soft = F.grid_sample(bitmap, grid, mode="bilinear", padding_mode="zeros", align_corners=False)
    return soft + ((soft >= 0.5).to(soft.dtype) - soft).detach()


def project(image, clean, epsilon):
    return torch.maximum(torch.minimum(image, clean + epsilon), clean - epsilon).clamp(0, 1)


def source_objective(source, target, text, local=True):
    sg, sl = source
    tg, tl = target
    score = F.cosine_similarity(sg, tg.detach(), dim=-1).mean()
    score = score + F.cosine_similarity(sg, text, dim=-1).mean()
    if local:
        score = score + F.cosine_similarity(sl, tl.detach(), dim=-1).mean()
    return score


def target_objective(target, source, text, pull=1., push=.5):
    return (pull * F.cosine_similarity(target[0], text, dim=-1).mean()
            - push * F.cosine_similarity(target[0], source[0].detach(), dim=-1).mean())


def optimize(image, target_texts, surrogates, config=None, device="cpu", progress=None):
    """Return (PNG-ready PIL image, audit dict). Surrogates implement two feature methods."""
    config = config or CottaConfig()
    if not target_texts or any(not t.strip() for t in target_texts):
        raise ValueError("At least one nonempty target string is required")
    if not surrogates and config.variant != "trigger_only":
        raise ValueError("Gradient optimization requires at least one surrogate")
    device = torch.device(device)
    clean_array = np.array(image.convert("RGB"))
    clean = torch.tensor(clean_array, device=device, dtype=torch.float32).permute(2, 0, 1)[None] / 255
    height, width = clean.shape[-2:]
    epsilon = config.epsilon / 255
    bitmap = text_bitmap(target_texts[0], config.font_size, config.wrap_chars).to(device)
    scale = torch.tensor(1., device=device, requires_grad=True)
    angle = torch.tensor(0., device=device, requires_grad=True)
    geometry = torch.optim.Adam([scale, angle], lr=config.geometry_lr)
    # Add light text on dark pixels and dark text on light pixels, without saturation.
    direction = torch.where(clean < .5, 1., -1.) * epsilon
    use_trigger = config.variant != "no_trigger"
    with torch.no_grad():
        initial_mask = transformed_mask(bitmap, height, width, scale, angle)
        target_base = initial_mask.expand_as(clean).clone()
    noise = torch.zeros_like(clean, requires_grad=True)
    target_noise = torch.zeros_like(clean, requires_grad=True)
    embeddings = [s.text_features(target_texts).detach() for s in surrogates]
    rng = random.Random(config.seed)
    history = []

    def attacked():
        mask = transformed_mask(bitmap, height, width, scale, angle) if use_trigger else 0
        return project(clean + mask * direction + noise, clean, epsilon)

    if config.variant != "trigger_only":
        for step in range(config.steps):
            geometry.zero_grad(set_to_none=True)
            src = attacked()
            target = project(target_base + target_noise, target_base, epsilon)
            index = rng.randrange(len(target_texts))
            source_features = [s.image_features(src) for s in surrogates]
            if config.variant != "static_target":
                tgt_features = [s.image_features(target) for s in surrogates]
                target_score = sum(target_objective(t, a, e[index:index + 1], config.pull, config.push)
                                   for t, a, e in zip(tgt_features, source_features, embeddings)) / len(surrogates)
                gradient, = torch.autograd.grad(target_score, target_noise)
                if not torch.isfinite(gradient).all():
                    raise FloatingPointError("Non-finite target gradient")
                with torch.no_grad():
                    target_noise.add_(config.target_step / 255 * gradient.sign()).clamp_(-epsilon, epsilon)
                    target = project(target_base + target_noise, target_base, epsilon)
                del tgt_features, target_score, gradient
            with torch.no_grad():
                target_features = [s.image_features(target) for s in surrogates]
            score = sum(source_objective(a, t, e[index:index + 1], config.variant != "no_local")
                        for a, t, e in zip(source_features, target_features, embeddings)) / len(surrogates)
            if not torch.isfinite(score):
                raise FloatingPointError("Non-finite surrogate objective")
            variables = [noise, scale, angle] if use_trigger else [noise]
            gradients = torch.autograd.grad(score, variables)
            if not all(torch.isfinite(g).all() for g in gradients):
                raise FloatingPointError("Non-finite source/geometry gradient")
            with torch.no_grad():
                noise.add_(config.source_step / 255 * gradients[0].sign()).clamp_(-epsilon, epsilon)
            if use_trigger:
                scale.grad, angle.grad = -gradients[1], -gradients[2]
                geometry.step()
                with torch.no_grad():
                    scale.clamp_(.1, 10.)
                    angle.clamp_(-math.pi, math.pi)
            if step == 0 or (step + 1) % 10 == 0 or step + 1 == config.steps:
                record = {"step": step + 1, "objective_before_update": score.item(),
                          "scale": scale.item(), "angle_radians": angle.item(), "text_variant": index}
                history.append(record)
                if progress:
                    progress(record)
            del source_features, target_features, score, gradients, src, target
    with torch.no_grad():
        array = (attacked()[0].permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.int16)
    original = clean_array.astype(np.int16)
    # Integer export also obeys a fractional budget; rounding must not enlarge it.
    budget = math.floor(config.epsilon)
    array = np.maximum(np.minimum(array, original + budget), original - budget).clip(0, 255).astype(np.uint8)
    delta = array.astype(np.float64) - original
    mse = float(np.square(delta).mean())
    metadata = {"config": asdict(config), "target_texts": list(target_texts),
                "surrogates": [s.metadata for s in surrogates], "device": str(device),
                "history": history, "scale": scale.item(), "angle_radians": angle.item(),
                "linf_8bit": float(np.abs(delta).max()), "mean_abs_8bit": float(np.abs(delta).mean()),
                "psnr_db": 10 * math.log10(255 ** 2 / mse) if mse else None,
                "size": [width, height], "iterations": 0 if config.variant == "trigger_only" else config.steps}
    return Image.fromarray(array), metadata
