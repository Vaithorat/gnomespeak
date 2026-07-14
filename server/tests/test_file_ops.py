import pytest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.file_ops import FileOps


class TestFileOps:
    def setup_method(self):
        self.ops = FileOps()
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_dir_current(self):
        result = self.ops.list_dir(".")
        assert result["success"] is True
        assert "Contents of" in result["message"]

    def test_list_dir_existing(self):
        test_dir = os.path.join(self.tmpdir, "test_dir")
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "file1.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(test_dir, "file2.txt"), "w") as f:
            f.write("world")

        result = self.ops.list_dir(test_dir)
        assert result["success"] is True
        assert "file1.txt" in result["message"]
        assert "file2.txt" in result["message"]

    def test_list_dir_nonexistent(self):
        result = self.ops.list_dir("C:\\nonexistent_path_12345")
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_list_dir_not_a_directory(self):
        test_file = os.path.join(self.tmpdir, "file.txt")
        with open(test_file, "w") as f:
            f.write("content")
        result = self.ops.list_dir(test_file)
        assert result["success"] is False
        assert "not a directory" in result["message"].lower()

    def test_list_dir_shows_subdirectories(self):
        test_dir = os.path.join(self.tmpdir, "with_subdir")
        os.makedirs(os.path.join(test_dir, "subfolder"))
        result = self.ops.list_dir(test_dir)
        assert result["success"] is True
        assert "subfolder/" in result["message"]

    def test_navigate_existing_path(self):
        with patch("handlers.file_ops.os.startfile") as mock_start:
            result = self.ops.navigate(self.tmpdir)
            assert result["success"] is True
            mock_start.assert_called_once()

    def test_navigate_nonexistent_path(self):
        result = self.ops.navigate("C:\\nonexistent_path_12345")
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_create_file(self):
        test_file = os.path.join(self.tmpdir, "new_file.txt")
        result = self.ops.create_file(test_file, "Hello World")
        assert result["success"] is True
        assert os.path.exists(test_file)
        with open(test_file) as f:
            assert f.read() == "Hello World"

    def test_create_file_empty_content(self):
        test_file = os.path.join(self.tmpdir, "empty_file.txt")
        result = self.ops.create_file(test_file)
        assert result["success"] is True
        assert os.path.exists(test_file)

    def test_create_folder(self):
        test_folder = os.path.join(self.tmpdir, "new_folder")
        result = self.ops.create_folder(test_folder)
        assert result["success"] is True
        assert os.path.isdir(test_folder)

    def test_create_folder_nested(self):
        test_folder = os.path.join(self.tmpdir, "a", "b", "c")
        result = self.ops.create_folder(test_folder)
        assert result["success"] is True
        assert os.path.isdir(test_folder)

    @pytest.mark.parametrize("action,args_checker", [
        ("list_dir", lambda r: r["success"] is True),
        ("create_file", lambda r: r["success"] is True),
        ("create_folder", lambda r: r["success"] is True),
        ("navigate", lambda r: r["success"] is True),
    ])
    def test_non_destructive_operations_return_dicts(self, action, args_checker):
        if action == "list_dir":
            result = self.ops.list_dir(self.tmpdir)
        elif action == "create_file":
            result = self.ops.create_file(os.path.join(self.tmpdir, "f.txt"))
        elif action == "create_folder":
            result = self.ops.create_folder(os.path.join(self.tmpdir, "d"))
        elif action == "navigate":
            with patch("handlers.file_ops.os.startfile"):
                result = self.ops.navigate(self.tmpdir)
        assert isinstance(result, dict)
        assert "success" in result
        assert "message" in result
        assert args_checker(result)
