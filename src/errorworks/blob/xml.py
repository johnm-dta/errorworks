"""S3-shaped XML response helpers for ChaosBlob."""

from __future__ import annotations

from typing import cast
from xml.etree import ElementTree

from errorworks.blob.store import BlobListPage

S3_XML_NAMESPACE = "http://s3.amazonaws.com/doc/2006-03-01/"
ElementTree.register_namespace("", S3_XML_NAMESPACE)


def error_xml(code: str, message: str, *, resource: str | None = None, request_id: str | None = None) -> bytes:
    """Return an S3-style error document."""
    root = ElementTree.Element(_s3_tag("Error"))
    ElementTree.SubElement(root, _s3_tag("Code")).text = code
    ElementTree.SubElement(root, _s3_tag("Message")).text = message
    if resource is not None:
        ElementTree.SubElement(root, _s3_tag("Resource")).text = resource
    if request_id is not None:
        ElementTree.SubElement(root, _s3_tag("RequestId")).text = request_id
    return _to_xml_bytes(root)


def list_objects_v2_xml(
    bucket: str,
    prefix: str,
    max_keys: int,
    continuation_token: str | None,
    page: BlobListPage,
) -> bytes:
    """Return an S3-style ListObjectsV2 response document."""
    root = ElementTree.Element(_s3_tag("ListBucketResult"))
    ElementTree.SubElement(root, _s3_tag("Name")).text = bucket
    ElementTree.SubElement(root, _s3_tag("Prefix")).text = prefix
    ElementTree.SubElement(root, _s3_tag("KeyCount")).text = str(len(page.objects))
    ElementTree.SubElement(root, _s3_tag("MaxKeys")).text = str(max_keys)
    ElementTree.SubElement(root, _s3_tag("IsTruncated")).text = str(page.is_truncated).lower()
    if continuation_token is not None:
        ElementTree.SubElement(root, _s3_tag("ContinuationToken")).text = continuation_token
    if page.next_continuation_token is not None:
        ElementTree.SubElement(root, _s3_tag("NextContinuationToken")).text = page.next_continuation_token

    for obj in page.objects:
        contents = ElementTree.SubElement(root, _s3_tag("Contents"))
        ElementTree.SubElement(contents, _s3_tag("Key")).text = obj.key
        ElementTree.SubElement(contents, _s3_tag("LastModified")).text = obj.last_modified_utc
        ElementTree.SubElement(contents, _s3_tag("ETag")).text = obj.etag
        ElementTree.SubElement(contents, _s3_tag("Size")).text = str(obj.size)
        ElementTree.SubElement(contents, _s3_tag("StorageClass")).text = "STANDARD"

    return _to_xml_bytes(root)


def _s3_tag(name: str) -> str:
    return f"{{{S3_XML_NAMESPACE}}}{name}"


def _to_xml_bytes(root: ElementTree.Element) -> bytes:
    return cast(bytes, ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))
