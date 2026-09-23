"""Real S3-compatible ObjectStorageAdapter implementation — Sprint 3 (audio) / Sprint 7 (retention).

Local dev already has a real (non-fake) object store via `minio` at S3_ENDPOINT in .env.example —
this module is the adapter built against `app.adapters.interfaces.ObjectStorageAdapter`.
"""

from __future__ import annotations


class S3ObjectStorage:
    def __init__(self, *, endpoint: str, bucket: str) -> None:
        raise NotImplementedError("S3 storage adapter lands alongside audio work in Sprint 3")
