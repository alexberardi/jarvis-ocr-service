"""Tests for app/image_resolver.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.image_resolver import (
    ImageResolverError,
    _infer_content_type,
    _resolve_https,
    _resolve_local_path,
    _resolve_minio,
    _resolve_s3,
    resolve_image,
)


class TestResolveImage:
    """Tests for resolve_image dispatch function."""

    def test_missing_kind(self):
        with pytest.raises(ImageResolverError, match="must have 'kind' and 'value'"):
            resolve_image({"value": "some/path"})

    def test_missing_value(self):
        with pytest.raises(ImageResolverError, match="must have 'kind' and 'value'"):
            resolve_image({"kind": "local_path"})

    def test_pdf_rejection(self):
        with pytest.raises(ImageResolverError, match="PDF files are not supported"):
            resolve_image({"kind": "local_path", "value": "/data/images/doc.pdf"})

    def test_pdf_rejection_case_insensitive(self):
        with pytest.raises(ImageResolverError, match="PDF files are not supported"):
            resolve_image({"kind": "s3", "value": "s3://bucket/Document.PDF"})

    def test_unknown_kind(self):
        with pytest.raises(ImageResolverError, match="Unknown image kind"):
            resolve_image({"kind": "ftp", "value": "ftp://server/img.png"})

    def test_db_kind_not_supported(self):
        with pytest.raises(ImageResolverError, match="not yet supported"):
            resolve_image({"kind": "db", "value": "some-db-id"})

    def test_local_path_dispatch(self, tmp_path):
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"PNG_DATA")
        with patch("app.image_resolver._resolve_local_path", return_value=(b"PNG_DATA", "image/png")) as mock_fn:
            result = resolve_image({"kind": "local_path", "value": str(img_file)})
        mock_fn.assert_called_once()

    def test_s3_dispatch(self):
        with patch("app.image_resolver._resolve_s3", return_value=(b"DATA", "image/png")) as mock_fn:
            resolve_image({"kind": "s3", "value": "s3://bucket/key.png"})
        mock_fn.assert_called_once()

    def test_minio_dispatch(self):
        with patch("app.image_resolver._resolve_minio", return_value=(b"DATA", "image/png")) as mock_fn:
            resolve_image({"kind": "minio", "value": "minio://bucket/key.png"})
        mock_fn.assert_called_once()


class TestResolveLocalPath:
    """Tests for _resolve_local_path."""

    @pytest.fixture(autouse=True)
    def _image_root(self, tmp_path, monkeypatch):
        # Confine the resolver to the test's tmp dir instead of /data/images.
        monkeypatch.setattr("app.image_resolver._IMAGE_ROOT", tmp_path)

    def test_success_absolute_path(self, tmp_path):
        img = tmp_path / "image.jpg"
        img.write_bytes(b"JPEG_DATA")
        data, ct = _resolve_local_path(str(img))
        assert data == b"JPEG_DATA"
        assert ct == "image/jpeg"

    def test_success_relative_path(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "image.png").write_bytes(b"PNG")
        data, ct = _resolve_local_path("sub/image.png")
        assert data == b"PNG"
        assert ct == "image/png"

    def test_file_not_found(self):
        with pytest.raises(ImageResolverError, match="not found"):
            _resolve_local_path("missing.png")

    def test_absolute_path_outside_root_rejected(self, tmp_path):
        with pytest.raises(ImageResolverError, match="escapes"):
            _resolve_local_path("/etc/passwd")

    def test_parent_traversal_rejected(self, tmp_path):
        # A ../ escape out of the image root must be refused, not read.
        secret = tmp_path.parent / "secret.png"
        secret.write_bytes(b"TOPSECRET")
        with pytest.raises(ImageResolverError, match="escapes"):
            _resolve_local_path("../secret.png")

    def test_directory_not_file(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(ImageResolverError, match="not a file"):
            _resolve_local_path(str(d))

    def test_content_type_png(self, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"PNG")
        _, ct = _resolve_local_path(str(img))
        assert ct == "image/png"

    def test_content_type_gif(self, tmp_path):
        img = tmp_path / "anim.gif"
        img.write_bytes(b"GIF89a")
        _, ct = _resolve_local_path(str(img))
        assert ct == "image/gif"

    def test_unknown_extension_defaults_to_png(self, tmp_path):
        img = tmp_path / "data.xyz"
        img.write_bytes(b"UNKNOWN")
        _, ct = _resolve_local_path(str(img))
        assert ct == "image/png"


class TestResolveS3:
    """Tests for _resolve_s3."""

    def test_success(self):
        mock_body = MagicMock()
        mock_body.read.return_value = b"IMAGE_BYTES"
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/jpeg",
        }
        with patch("app.image_resolver.boto3.client", return_value=mock_s3):
            data, ct = _resolve_s3("s3://my-bucket/images/photo.jpg")

        assert data == b"IMAGE_BYTES"
        assert ct == "image/jpeg"
        mock_s3.get_object.assert_called_once_with(Bucket="my-bucket", Key="images/photo.jpg")

    def test_no_such_key(self):
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )
        with patch("app.image_resolver.boto3.client", return_value=mock_s3):
            with pytest.raises(ImageResolverError, match="not found"):
                _resolve_s3("s3://bucket/missing.png")

    def test_access_denied(self):
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
            "GetObject",
        )
        with patch("app.image_resolver.boto3.client", return_value=mock_s3):
            with pytest.raises(ImageResolverError, match="Access denied"):
                _resolve_s3("s3://bucket/private.png")

    def test_no_credentials(self):
        from botocore.exceptions import NoCredentialsError

        with patch("app.image_resolver.boto3.client", side_effect=NoCredentialsError()):
            with pytest.raises(ImageResolverError, match="No AWS credentials"):
                _resolve_s3("s3://bucket/img.png")

    def test_https_url_delegates(self):
        with patch("app.image_resolver._resolve_https", return_value=(b"DATA", "image/png")) as mock_fn:
            _resolve_s3("https://s3.amazonaws.com/bucket/key.png")
        mock_fn.assert_called_once()

    def test_invalid_uri_format(self):
        with pytest.raises(ImageResolverError, match="Invalid S3 URI"):
            _resolve_s3("s3://")

    def test_content_type_inferred_when_missing(self):
        mock_body = MagicMock()
        mock_body.read.return_value = b"DATA"
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": mock_body}
        with patch("app.image_resolver.boto3.client", return_value=mock_s3):
            _, ct = _resolve_s3("s3://bucket/photo.webp")
        assert ct == "image/webp"


class TestResolveMinio:
    """Tests for _resolve_minio."""

    def test_converts_minio_to_s3(self):
        with patch("app.image_resolver._resolve_s3", return_value=(b"DATA", "image/png")) as mock_fn:
            _resolve_minio("minio://bucket/key.png")
        mock_fn.assert_called_once_with("s3://bucket/key.png")

    def test_passes_s3_uri_through(self):
        with patch("app.image_resolver._resolve_s3", return_value=(b"DATA", "image/png")) as mock_fn:
            _resolve_minio("s3://bucket/key.png")
        mock_fn.assert_called_once_with("s3://bucket/key.png")


import socket


def _addrinfo_for(ip: str):
    def _f(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]
    return _f


def _ok_response(content=b"IMAGE_BYTES", content_type="image/jpeg"):
    resp = MagicMock()
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.raise_for_status = MagicMock()
    return resp


class TestResolveHttps:
    """Tests for _resolve_https."""

    def test_success(self):
        with patch("app.image_resolver.socket.getaddrinfo", _addrinfo_for("93.184.216.34")), \
             patch("app.image_resolver.requests.get", return_value=_ok_response()):
            data, ct = _resolve_https("https://example.com/img.jpg")
        assert data == b"IMAGE_BYTES"
        assert ct == "image/jpeg"

    def test_request_exception(self):
        import requests as req

        with patch("app.image_resolver.socket.getaddrinfo", _addrinfo_for("93.184.216.34")), \
             patch("app.image_resolver.requests.get", side_effect=req.exceptions.ConnectionError("fail")):
            with pytest.raises(ImageResolverError, match="Failed to fetch"):
                _resolve_https("https://example.com/img.jpg")

    def test_blocks_loopback(self):
        with patch("app.image_resolver.socket.getaddrinfo", _addrinfo_for("127.0.0.1")):
            with pytest.raises(ImageResolverError, match="SSRF guard"):
                _resolve_https("http://localhost/img.jpg")

    def test_blocks_private_network(self):
        with patch("app.image_resolver.socket.getaddrinfo", _addrinfo_for("10.1.2.3")):
            with pytest.raises(ImageResolverError, match="SSRF guard"):
                _resolve_https("https://intranet.example/img.jpg")

    def test_blocks_cloud_metadata(self):
        # 169.254.169.254 (link-local) — the classic SSRF metadata target.
        with patch("app.image_resolver.socket.getaddrinfo", _addrinfo_for("169.254.169.254")):
            with pytest.raises(ImageResolverError, match="SSRF guard"):
                _resolve_https("http://metadata.example/latest/meta-data/")

    def test_rejects_non_http_scheme(self):
        with pytest.raises(ImageResolverError, match="scheme"):
            _resolve_https("file:///etc/passwd")

    def test_redirect_to_internal_is_blocked(self):
        def addr(host, *args, **kwargs):
            ip = "127.0.0.1" if host == "internal.local" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]

        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.is_permanent_redirect = False
        redirect.headers = {"Location": "https://internal.local/secret"}

        with patch("app.image_resolver.socket.getaddrinfo", side_effect=addr), \
             patch("app.image_resolver.requests.get", return_value=redirect):
            with pytest.raises(ImageResolverError, match="SSRF guard"):
                _resolve_https("https://example.com/img.jpg")


class TestInferContentType:
    """Tests for _infer_content_type."""

    def test_png(self):
        assert _infer_content_type("photo.png") == "image/png"

    def test_jpg(self):
        assert _infer_content_type("photo.jpg") == "image/jpeg"

    def test_jpeg(self):
        assert _infer_content_type("photo.jpeg") == "image/jpeg"

    def test_tiff(self):
        assert _infer_content_type("scan.tiff") == "image/tiff"

    def test_unknown_defaults_to_png(self):
        assert _infer_content_type("file.xyz") == "image/png"

    def test_no_extension_defaults_to_png(self):
        assert _infer_content_type("file") == "image/png"
