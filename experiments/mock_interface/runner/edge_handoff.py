"""TEST_ONLY / NOT_PRODUCTION_EDGE_INTAKE: no Atlas, MQTT, Cloud or API."""

from mock_loader import payload_hash, plain


def receive_validated(payload, *, context):
    """Sibling consumer of the SAME validated payload, never consumes Risk output.

    Return unchanged payload content to the runner's evidence recorder. Exact input
    bytes are preserved separately by the runner. No production storage is implied.
    """
    return {
        "status": "ACCEPTED", "scope": "TEST_ONLY / NOT_PRODUCTION_EDGE_INTAKE",
        "source": context["source"], "payload_sha256": payload_hash(payload),
        "payload": plain(payload),
        "production_edge_intake": "NOT_IMPLEMENTED",
    }
