"""The reference vector files, pinned by sha256 and read only through here.

Copied unchanged from the API signature specification's reference vectors:
``hmac_v1_vectors.json`` (request signing) and ``webhook_hmac_v1_vectors.json``
(webhook signing). A copy that differs from the reference fails at import.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

TESTDATA = Path(__file__).parent / "testdata"

REQUEST_VECTORS_SHA256 = "a87df4921399dc14c7ceaa7e4c0dfa02495ad0400a5e722adfc0d3e3c1e064fe"
WEBHOOK_VECTORS_SHA256 = "15a6e1423708e8c3b9ec4fac7ee6eb383db56703605647e02308a29166722502"


def _load(name: str, sha256: str) -> Tuple[Path, List[Dict[str, Any]]]:
    path = TESTDATA / name
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != sha256:
        raise AssertionError(f"{name}: sha256 {digest}, expected {sha256}")
    if b"\r" in raw or b"\x00" in raw:
        raise AssertionError(f"{name}: the copy is not the reference bytes")
    return path, json.loads(raw.decode("utf-8"))


REQUEST_VECTORS_FILE, REQUEST_VECTORS = _load("hmac_v1_vectors.json", REQUEST_VECTORS_SHA256)
WEBHOOK_VECTORS_FILE, WEBHOOK_VECTORS = _load(
    "webhook_hmac_v1_vectors.json", WEBHOOK_VECTORS_SHA256
)
