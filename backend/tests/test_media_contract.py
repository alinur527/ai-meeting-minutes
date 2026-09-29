import io

import av
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from alem_contract.asgi import BodyLimitMiddleware
from alem_contract.audio import inspect_audio

from test_ai_integration import login_client, wav_bytes  # noqa: F401


@pytest.mark.parametrize(
    "extension,codec", [("wav", "pcm_s16le"), ("mp3", "libmp3lame"), ("m4a", "aac")]
)
def test_supported_media_decodes_and_uploads(database, tmp_path, extension, codec):
    path = tmp_path / ("audio." + extension)
    with (
        av.open(io.BytesIO(wav_bytes())) as source,
        av.open(
            str(path), "w", format="ipod" if extension == "m4a" else None
        ) as output,
    ):
        stream = output.add_stream(codec, rate=16000)
        stream.layout = "mono"
        for frame in source.decode(audio=0):
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    assert (
        950 <= inspect_audio(path, max_bytes=1000000, max_seconds=3).duration_ms <= 1200
    )
    client = login_client(database)
    response = client.post(
        "/meetings",
        files={"file": (path.name, path.read_bytes())},
        data={
            "title": "Медиа",
            "started_at": "2026-09-25T10:00:00Z",
            "timezone": "UTC",
            "participants_json": '[{"name":"Test"}]',
        },
    )
    assert response.status_code == 202, response.text


def test_request_limit_counts_chunked_body_and_content_length():
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=6)

    @app.post("/")
    async def upload(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        assert client.post("/", content=b"123456").json() == {"size": 6}
        assert client.post("/", content=b"1234567").status_code == 413
        assert client.post("/", content=iter([b"123", b"456", b"7"])).status_code == 413
