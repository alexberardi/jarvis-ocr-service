"""Tests for app/utils.py - Docker detection and environment checks."""

from unittest.mock import MagicMock, mock_open, patch

import pytest

from app.utils import is_macos, is_running_in_docker, validate_apple_vision_environment


class TestIsRunningInDocker:
    """Tests for is_running_in_docker()."""

    def test_returns_true_when_dockerenv_exists(self):
        """Detect Docker via /.dockerenv file."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = True
            assert is_running_in_docker() is True

    def test_returns_true_when_cgroup_contains_docker(self):
        """Detect Docker via /proc/self/cgroup containing 'docker'."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            with patch("builtins.open", mock_open(read_data="12:devices:/docker/abc123\n")):
                assert is_running_in_docker() is True

    def test_returns_true_when_cgroup_contains_containerd(self):
        """Detect Docker via /proc/self/cgroup containing 'containerd'."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            with patch("builtins.open", mock_open(read_data="12:devices:/containerd/abc123\n")):
                assert is_running_in_docker() is True

    def test_returns_false_when_not_in_docker(self):
        """Return False when no Docker indicators are found."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            with patch("builtins.open", mock_open(read_data="12:devices:/user.slice\n")):
                assert is_running_in_docker() is False

    def test_returns_false_when_cgroup_file_not_found(self):
        """Return False when /proc/self/cgroup does not exist (e.g., macOS)."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            with patch("builtins.open", side_effect=FileNotFoundError):
                assert is_running_in_docker() is False

    def test_returns_false_when_cgroup_permission_denied(self):
        """Return False when /proc/self/cgroup cannot be read."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            with patch("builtins.open", side_effect=PermissionError):
                assert is_running_in_docker() is False

    def test_dockerenv_checked_before_cgroup(self):
        """Return True immediately if /.dockerenv exists (skip cgroup check)."""
        with patch("app.utils.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = True
            # open should never be called since /.dockerenv is found first
            with patch("builtins.open") as mock_file:
                result = is_running_in_docker()
                assert result is True
                mock_file.assert_not_called()


class TestIsMacos:
    """Tests for is_macos()."""

    def test_returns_true_on_darwin(self):
        """Return True when platform.system() returns 'Darwin'."""
        with patch("app.utils.platform.system", return_value="Darwin"):
            assert is_macos() is True

    def test_returns_false_on_linux(self):
        """Return False when platform.system() returns 'Linux'."""
        with patch("app.utils.platform.system", return_value="Linux"):
            assert is_macos() is False

    def test_returns_false_on_windows(self):
        """Return False when platform.system() returns 'Windows'."""
        with patch("app.utils.platform.system", return_value="Windows"):
            assert is_macos() is False


class TestValidateAppleVisionEnvironment:
    """Tests for validate_apple_vision_environment()."""

    def test_raises_when_running_in_docker(self):
        """Raise RuntimeError if running in Docker."""
        with patch("app.utils.is_running_in_docker", return_value=True):
            with pytest.raises(RuntimeError, match="cannot run inside Docker"):
                validate_apple_vision_environment()

    def test_raises_when_not_macos(self):
        """Raise RuntimeError if not on macOS."""
        with patch("app.utils.is_running_in_docker", return_value=False):
            with patch("app.utils.is_macos", return_value=False):
                with pytest.raises(RuntimeError, match="only available on macOS"):
                    validate_apple_vision_environment()

    def test_succeeds_on_native_macos(self):
        """No error when running natively on macOS."""
        with patch("app.utils.is_running_in_docker", return_value=False):
            with patch("app.utils.is_macos", return_value=True):
                # Should not raise
                validate_apple_vision_environment()

    def test_docker_check_happens_before_macos_check(self):
        """Docker check takes priority over macOS check."""
        with patch("app.utils.is_running_in_docker", return_value=True):
            with patch("app.utils.is_macos") as mock_is_macos:
                with pytest.raises(RuntimeError, match="cannot run inside Docker"):
                    validate_apple_vision_environment()
                # is_macos should not be called if Docker check fails first
                mock_is_macos.assert_not_called()

    def test_error_message_includes_platform_when_not_macos(self):
        """Error message includes the current platform name."""
        with patch("app.utils.is_running_in_docker", return_value=False):
            with patch("app.utils.is_macos", return_value=False):
                with patch("app.utils.platform.system", return_value="Linux"):
                    with pytest.raises(RuntimeError, match="Linux"):
                        validate_apple_vision_environment()
