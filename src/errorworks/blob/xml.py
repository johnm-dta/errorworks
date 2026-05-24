"""S3-shaped XML response helpers for ChaosBlob."""

from __future__ import annotations

from typing import cast
from xml.etree import ElementTree

from errorworks.blob.store import BlobListPage


def error_xml(code: str, message: str, *, resource: str | None = None, request_id: str | None = None) -> bytes:
    """Return an S3-style error document."""
    root = ElementTree.Element("Error")
    ElementTree.SubElement(root, "Code").text = code
    ElementTree.SubElement(root, "Message").text = message
    if resource is not None:
        ElementTree.SubElement(root, "Resource").text = resource
    if request_id is not None:
        ElementTree.SubElement(root, "RequestId").text = request_id
    return _to_xml_bytes(root)


def list_objects_v2_xml(
    bucket: str,
    prefix: str,
    max_keys: int,
    continuation_token: str | None,
    page: BlobListPage,
) -> bytes:
    """Return an S3-style ListObjectsV2 response document."""
    root = ElementTree.Element("ListBucketResult")
    ElementTree.SubElement(root, "Name").text = bucket
    ElementTree.SubElement(root, "Prefix").text = prefix
    ElementTree.SubElement(root, "KeyCount").text = str(len(page.objects))
    ElementTree.SubElement(root, "MaxKeys").text = str(max_keys)
    ElementTree.SubElement(root, "IsTruncated").text = str(page.is_truncated).lower()
    if continuation_token is not None:
        ElementTree.SubElement(root, "ContinuationToken").text = continuation_token
    if page.next_continuation_token is not None:
        ElementTree.SubElement(root, "NextContinuationToken").text = page.next_continuation_token

    for obj in page.objects:
        contents = ElementTree.SubElement(root, "Contents")
        ElementTree.SubElement(contents, "Key").text = obj.key
        ElementTree.SubElement(contents, "LastModified").text = obj.last_modified_utc
        ElementTree.SubElement(contents, "ETag").text = obj.etag
        ElementTree.SubElement(contents, "Size").text = str(obj.size)
        ElementTree.SubElement(contents, "StorageClass").text = "STANDARD"

    return _to_xml_bytes(root)


def _to_xml_bytes(root: ElementTree.Element) -> bytes:
    return cast(bytes, ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))
