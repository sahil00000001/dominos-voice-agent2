"""
api/tts.py — Cartesia TTS serverless endpoint
==============================================
Receives text, calls Cartesia's REST TTS API with Priya's voice,
and returns raw MP3 audio bytes for the browser to play.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.error


VOICE_ID = "71a7ad14-091c-4e8e-a314-022ece01c121"
MODEL_ID  = "sonic-2024-10-19"


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = body.get("text", "").strip()

            if not text:
                self._json(400, {"error": "No text provided"})
                return

            cartesia_key = os.environ.get("CARTESIA_API_KEY", "")

            payload = {
                "transcript": text,
                "model_id": MODEL_ID,
                "voice": {"mode": "id", "id": VOICE_ID},
                "output_format": {
                    "container": "mp3",
                    "bit_rate": 128000,
                    "sample_rate": 44100,
                },
                "language": "en",
            }

            req = urllib.request.Request(
                "https://api.cartesia.ai/tts/bytes",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "X-API-Key": cartesia_key,
                    "Cartesia-Version": "2024-06-10",
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(req, timeout=20) as resp:
                audio_bytes = resp.read()

            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio_bytes)))
            self.end_headers()
            self.wfile.write(audio_bytes)

        except urllib.error.HTTPError as exc:
            body = exc.read()
            self._json(502, {"error": f"Cartesia error {exc.code}: {body.decode(errors='replace')}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *args):
        pass
