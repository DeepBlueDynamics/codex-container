import os

import pytest

try:
    import requests  # type: ignore
except ImportError:
    requests = None


INSTRUCTOR_URL = os.environ.get("INSTRUCTOR_SERVICE_URL", "http://localhost:8787/embed")


@pytest.mark.integration
def test_instructor_service_embed_endpoint():
    if requests is None:
        pytest.skip("requests not installed")

    payload = {
        "texts": ["hello world", "quick test"],
        "instruction": "Represent the text for semantic search",
        "normalize": True,
    }
    try:
        resp = requests.post(INSTRUCTOR_URL, json=payload, timeout=10)
    except Exception as exc:
        pytest.skip(f"Embedding service unreachable: {exc}")

    if resp.status_code >= 500:
        pytest.skip(f"Embedding service returned {resp.status_code}")

    assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:200]}"
    data = resp.json()

    # Basic shape checks
    embeddings = data.get("embeddings")
    assert embeddings is not None, f"No embeddings in response: {data}"
    assert isinstance(embeddings, list), "embeddings should be a list"
    assert len(embeddings) == 2, f"expected 2 embeddings, got {len(embeddings)}"
    assert all(isinstance(vec, list) and len(vec) > 0 for vec in embeddings), "embeddings should be non-empty vectors"

