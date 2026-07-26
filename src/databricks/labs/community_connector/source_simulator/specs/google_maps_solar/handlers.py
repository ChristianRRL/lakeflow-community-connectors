"""Custom simulator handler for the Solar API's binary ``geoTiff:get`` endpoint.

``geoTiff:get`` is the one Solar API endpoint whose response body is *not*
JSON: a plain REST call returns the raster file itself with an ``image/tiff``
content type.  The declarative spec can only render JSON from a corpus, so
``endpoints.yaml`` drops to this handler for that path.

The module lives beside the spec (rather than under the connector's source
directory) because it is simulator-only code: the connector never imports it,
and keeping it here keeps it out of the deployable merged connector file.
"""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

from databricks.labs.community_connector.source_simulator.cassette import (
    ResponseRecord,
)
from databricks.labs.community_connector.source_simulator.interceptor import (
    response_from_record,
)

#: Little-endian TIFF magic ("II", 42) plus the offset of the first IFD.
_TIFF_HEADER = b"II\x2a\x00\x08\x00\x00\x00"
_PAYLOAD_BYTES = 1024


def geo_tiff_handler(prep, spec, corpus):  # pylint: disable=unused-argument
    """Serve a deterministic pseudo-GeoTIFF for a ``geoTiff:get`` request.

    The payload is TIFF magic followed by bytes derived from the requested
    asset id, so each asset gets distinct but reproducible content and the
    connector exercises its real raw-bytes path (``response.content`` plus
    the ``Content-Type`` header) instead of a JSON stand-in.
    """
    url = prep.url or ""
    asset_id = (parse_qs(urlsplit(url).query).get("id") or ["unknown-asset"])[0]

    digest = hashlib.sha256(asset_id.encode("utf-8")).digest()
    filler = (digest * (_PAYLOAD_BYTES // len(digest) + 1))[:_PAYLOAD_BYTES]
    payload = _TIFF_HEADER + filler

    record = ResponseRecord(
        status_code=200,
        headers={
            "Content-Type": "image/tiff",
            "Content-Length": str(len(payload)),
        },
        body_text=None,
        body_b64=base64.b64encode(payload).decode("ascii"),
        encoding=None,
        url=url,
    )
    return response_from_record(record, prep)
