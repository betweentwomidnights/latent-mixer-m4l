import torch

from stable_audio_tools import get_pretrained_model
model, model_config = get_pretrained_model("stabilityai/stable-audio-open-1.0")
torch.save({"state_dict": model.pretransform.model.state_dict()}, "vae.ckpt")