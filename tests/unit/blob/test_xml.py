from __future__ import annotations

from xml.etree import ElementTree

from errorworks.blob.store import BlobListPage, BlobObject
from errorworks.blob.xml import error_xml, list_objects_v2_xml


def test_error_xml_uses_s3_error_shape() -> None:
    body = error_xml("NoSuchKey", "The specified key does not exist.", resource="/bucket/key")
    root = ElementTree.fromstring(body)
    assert root.tag == "Error"
    assert root.findtext("Code") == "NoSuchKey"
    assert root.findtext("Message") == "The specified key does not exist."
    assert root.findtext("Resource") == "/bucket/key"


def test_list_objects_v2_xml_includes_object_metadata() -> None:
    obj = BlobObject(
        bucket="bucket",
        key="docs/a.txt",
        body=b"abc",
        content_type="text/plain",
        etag="900150983cd24fb0d6963f7d28e17f72",
        last_modified_utc="2026-05-24T00:00:00+00:00",
        headers={},
        metadata={},
    )
    xml = list_objects_v2_xml(
        bucket="bucket",
        prefix="docs/",
        max_keys=1000,
        continuation_token=None,
        page=BlobListPage(objects=[obj], is_truncated=False, next_continuation_token=None),
    )
    root = ElementTree.fromstring(xml)
    assert root.findtext("Name") == "bucket"
    assert root.findtext("Prefix") == "docs/"
    assert root.findtext("Contents/Key") == "docs/a.txt"
    assert root.findtext("Contents/Size") == "3"
