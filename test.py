import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import wave

load_dotenv()


# Set up the wave file to save the output:
def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


api_key = os.getenv("GEMINI_API_KEYS")
if not api_key:
    raise RuntimeError("GEMINI_API_KEYS is missing.")

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-2.5-flash-preview-tts",
    contents="Say cheerfully: The Quick brown fox jumps over the lazy dog.",
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore",
                )
            )
        ),
    ),
)

data = response.candidates[0].content.parts[0].inline_data.data

file_name = "out.wav"
wave_file(file_name, data)  # Saves the file to current directory
