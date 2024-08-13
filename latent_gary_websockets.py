from flask import Flask
from flask_socketio import SocketIO, emit
import base64
import torch
import torchaudio
import io
import json
from pathlib import Path
from stable_audio_tools.models.factory import create_model_from_config
from stable_audio_tools.models.utils import load_ckpt_state_dict
from stable_audio_tools.training.utils import copy_state_dict
from pydantic import BaseModel, ValidationError
import numpy as np

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=100 * 1024 * 1024, ping_timeout=600, ping_interval=300)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SAMPLE_RATE = 44100

# Load the VAE model globally
config_path = Path("vae_config.json")
checkpoint_path = Path("vae.ckpt")
with config_path.open() as f:
    config = json.load(f)
vae = create_model_from_config(config)
copy_state_dict(vae, load_ckpt_state_dict(str(checkpoint_path)))
MODEL = vae.to(DEVICE).eval().requires_grad_(False)
print("Model loaded globally")

# Pydantic model for transformations
class TransformParams(BaseModel):
    scale: float
    rotate: float
    nonlinear: float
    scale_active: bool
    rotate_active: bool
    nonlinear_active: bool

# Transform functions
def weighted_average(vec1, vec2, weight):
    return (1 - weight) * vec1 + weight * vec2

def scale_transform(vec, factor):
    return vec * factor

def rotate_transform(vec, factor):
    angle = factor * np.pi
    cos, sin = np.cos(angle), np.sin(angle)
    rotation_matrix = torch.tensor(
        [[cos, -sin], [sin, cos]], device=vec.device, dtype=torch.float32
    )
    orig_shape = vec.shape
    vec_2d = vec.reshape(-1, 2)
    rotated = torch.matmul(vec_2d, rotation_matrix)
    return rotated.reshape(orig_shape)

def nonlinear_transform(vec, factor):
    return torch.tanh(vec * (1 + factor))

@socketio.on('interpolate_audio')
@torch.no_grad()  # Ensure no gradients are computed
def handle_interpolate_audio(data):
    try:
        print("Received interpolation request")

        try:
            buffer1 = base64.b64decode(data['buffer1'])
            buffer2 = base64.b64decode(data['buffer2'])
        except Exception as e:
            print(f"Error decoding buffers: {e}")
            emit('error', {'message': f"Error decoding buffers: {e}"})
            return

        try:
            tensor1, sr1 = torchaudio.load(io.BytesIO(buffer1))
            tensor2, sr2 = torchaudio.load(io.BytesIO(buffer2))
            print(f"Loaded audio buffers with shapes: {tensor1.shape}, {tensor2.shape}")

            # Resample if the sample rate is not 44100 Hz
            if sr1 != SAMPLE_RATE:
                resampler = torchaudio.transforms.Resample(sr1, SAMPLE_RATE)
                tensor1 = resampler(tensor1)
            if sr2 != SAMPLE_RATE:
                resampler = torchaudio.transforms.Resample(sr2, SAMPLE_RATE)
                tensor2 = resampler(tensor2)
            print(f"Resampled audio to {SAMPLE_RATE} Hz if needed")
            
            # Convert mono to stereo if necessary
            if tensor1.shape[0] == 1:
                tensor1 = torch.cat([tensor1, tensor1], dim=0)  # Duplicate the mono channel to create stereo
            if tensor2.shape[0] == 1:
                tensor2 = torch.cat([tensor2, tensor2], dim=0)  # Duplicate the mono channel to create stereo
            print(f"Adjusted to stereo if needed: {tensor1.shape}, {tensor2.shape}")
        except Exception as e:
            print(f"Error loading or adjusting audio buffers: {e}")
            emit('error', {'message': f"Error loading or adjusting audio buffers: {e}"})
            return

        # Ensure both tensors have the same length
        min_length = min(tensor1.shape[1], tensor2.shape[1])
        tensor1 = tensor1[:, :min_length]
        tensor2 = tensor2[:, :min_length]

        # Move tensors to the same device as the model
        tensor1 = tensor1.to(DEVICE)
        tensor2 = tensor2.to(DEVICE)

        # Encode audio
        try:
            encoded1 = MODEL.encode(tensor1.unsqueeze(0))
            encoded2 = MODEL.encode(tensor2.unsqueeze(0))
            print(f"Encoded audio: {encoded1.shape}, {encoded2.shape}")
        except Exception as e:
            print(f"Error encoding audio: {e}")
            emit('error', {'message': f"Error encoding audio: {e}"})
            return

        # Weighted average interpolation
        try:
            interpolated = weighted_average(encoded1, encoded2, data['x'])
            print("Applied weighted average interpolation")
        except Exception as e:
            print(f"Error during interpolation: {e}")
            emit('error', {'message': f"Error during interpolation: {e}"})
            return

        # Parse and apply transformations
        try:
            transform_params = TransformParams(**data['transforms'])
        except ValidationError as e:
            print(f"Transform parameters validation error: {e}")
            emit('error', {'message': f"Transform parameters validation error: {e}"})
            return

        if transform_params.scale_active:
            interpolated = scale_transform(interpolated, transform_params.scale)
        if transform_params.rotate_active:
            interpolated = rotate_transform(interpolated, transform_params.rotate)
        if transform_params.nonlinear_active:
            interpolated = nonlinear_transform(interpolated, transform_params.nonlinear)
        print("Applied transformations")

        # Decode the result
        try:
            decoded = MODEL.decode(interpolated)
            output_audio = decoded.squeeze(0).cpu()
            print("Decoded audio")
        except Exception as e:
            print(f"Error decoding audio: {e}")
            emit('error', {'message': f"Error decoding audio: {e}"})
            return

        # Convert to WAV format
        try:
            output_buffer = io.BytesIO()
            torchaudio.save(output_buffer, output_audio, SAMPLE_RATE, format="wav")
            output_buffer.seek(0)
            output_base64 = base64.b64encode(output_buffer.read()).decode('utf-8')
            print("Processed audio and sending back to client")
            emit('interpolation_complete', {'audio_data': output_base64})
        except Exception as e:
            print(f"Error processing audio: {e}")
            emit('error', {'message': f"Error processing audio: {e}"})
    except Exception as e:
        print(f"General error in handle_interpolate_audio: {e}")
        emit('error', {'message': f"General error: {e}"})



@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('connect_response', {'status': 'connected'})

@socketio.on('test_event')
def handle_test_event(data):
    print('Received test event:', data)
    emit('test_event_response', {'message': 'Echo: ' + data['message']})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
