"""
api/transcribe.py — Deepgram STT serverless endpoint
=====================================================
Receives raw audio bytes from the browser (webm/ogg/wav),
sends to Deepgram's prerecorded transcription API,
and returns the transcript text as JSON.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.error
import urllib.parse


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._json(400, {"error": "No audio data", "transcript": ""})
                return

            audio_data = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "audio/webm")
            deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "")

            params = urllib.parse.urlencode({
                "model": "nova-2",
                "smart_format": "true",
                "language": "en-IN",
                "punctuate": "true",
            })
            url = f"https://api.deepgram.com/v1/listen?{params}"

            req = urllib.request.Request(
                url,
                data=audio_data,
                headers={
                    "Authorization": f"Token {deepgram_key}",
                    "Content-Type": content_type,
                },
            )

            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read())

            transcript = (
                result
                .get("results", {})
                .get("channels", [{}])[0]
                .get("alternatives", [{}])[0]
                .get("transcript", "")
            )

            self._json(200, {"transcript": transcript})

        except urllib.error.HTTPError as exc:
            body = exc.read()
            self._json(502, {
                "error": f"Deepgram error {exc.code}: {body.decode(errors='replace')}",
                "transcript": "",
            })
        except Exception as exc:
            self._json(500, {"error": str(exc), "transcript": ""})

    def _json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
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
