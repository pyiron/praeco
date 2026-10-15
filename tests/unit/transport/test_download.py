import os
import unittest
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from praeco.exceptions import ValidationError
from praeco.transport.download import write_response_to_path

# Reference MD5 digests (RFC 1321 test suite and the common "hello world").
MD5_ABC = "900150983cd24fb0d6963f7d28e17f72"
MD5_HELLO_WORLD = "5eb63bbbe01eeed093cb22bb8f5acdc3"


class StreamingResponse:
    """Minimal stand-in for a streamed `requests.Response`."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        stream_exc: Exception | None = None,
    ):
        self._chunks = chunks
        self._stream_exc = stream_exc
        self.chunk_sizes: list[int] = []
        self.closed = False

    def iter_content(self, chunk_size: int = 1) -> Iterator[bytes]:
        self.chunk_sizes.append(chunk_size)
        yield from self._chunks
        if self._stream_exc is not None:
            raise self._stream_exc

    def close(self) -> None:
        self.closed = True


def _write(response: StreamingResponse, path: Path, **kwargs: Any) -> Path:
    return write_response_to_path(cast(Any, response), path, **kwargs)


def _tree(root: Path) -> list[str]:
    """Return every path below `root`, including hidden temporary files."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class TestWriteResponseToPath(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_writes_streamed_chunks_and_returns_target(self):
        response = StreamingResponse([b"hello", b" ", b"world"])
        target = self.root / "file.bin"

        result = _write(response, target, md5=MD5_HELLO_WORLD, size=11)

        self.assertIsInstance(result, Path)
        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), b"hello world")
        self.assertEqual(_tree(self.root), ["file.bin"])
        self.assertTrue(response.closed)

    def test_creates_missing_parent_directories(self):
        response = StreamingResponse([b"abc"])
        target = self.root / "a" / "b" / "file.txt"

        result = _write(response, target)

        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), b"abc")

    def test_existing_target_raises_without_overwrite(self):
        target = self.root / "file.txt"
        _ = target.write_bytes(b"original")
        response = StreamingResponse([b"new"])

        with self.assertRaises(FileExistsError):
            _write(response, target)

        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(_tree(self.root), ["file.txt"])
        self.assertTrue(response.closed)

    def test_overwrite_replaces_existing_target(self):
        target = self.root / "file.txt"
        _ = target.write_bytes(b"original contents")
        response = StreamingResponse([b"abc"])

        result = _write(response, target, overwrite=True, md5=MD5_ABC, size=3)

        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), b"abc")
        self.assertEqual(_tree(self.root), ["file.txt"])
        self.assertTrue(response.closed)

    def test_md5_mismatch_raises_and_leaves_no_files(self):
        response = StreamingResponse([b"abc"])
        target = self.root / "file.txt"

        with self.assertRaises(ValidationError):
            _write(response, target, md5=MD5_HELLO_WORLD)

        self.assertEqual(_tree(self.root), [])
        self.assertTrue(response.closed)

    def test_size_mismatch_raises_and_leaves_no_files(self):
        for size in (2, 4, 0):
            with self.subTest(size=size):
                response = StreamingResponse([b"abc"])
                target = self.root / "file.txt"

                with self.assertRaises(ValidationError):
                    _write(response, target, size=size)

                self.assertEqual(_tree(self.root), [])
                self.assertTrue(response.closed)

    def test_failed_verification_keeps_created_parents_but_no_files(self):
        response = StreamingResponse([b"abc"])
        target = self.root / "sub" / "file.txt"

        with self.assertRaises(ValidationError):
            _write(response, target, md5=MD5_HELLO_WORLD)

        self.assertEqual(_tree(self.root), ["sub"])

    def test_failed_overwrite_keeps_existing_target(self):
        target = self.root / "file.txt"
        _ = target.write_bytes(b"original")
        response = StreamingResponse([b"abc"])

        with self.assertRaises(ValidationError):
            _write(response, target, overwrite=True, md5=MD5_HELLO_WORLD)

        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(_tree(self.root), ["file.txt"])

    def test_md5_is_compared_case_insensitively(self):
        response = StreamingResponse([b"abc"])
        target = self.root / "file.txt"

        _write(response, target, md5=MD5_ABC.upper())

        self.assertEqual(target.read_bytes(), b"abc")

    def test_none_md5_and_size_skip_verification(self):
        response = StreamingResponse([b"any", b"thing"])
        target = self.root / "file.txt"

        result = _write(response, target, md5=None, size=None)

        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), b"anything")

    def test_empty_chunks_are_ignored(self):
        response = StreamingResponse([b"", b"ab", b"", b"c", b""])
        target = self.root / "file.txt"

        _write(response, target, md5=MD5_ABC, size=3)

        self.assertEqual(target.read_bytes(), b"abc")

    def test_empty_body_writes_empty_file(self):
        response = StreamingResponse([])
        target = self.root / "empty.txt"

        _write(response, target, size=0)

        self.assertEqual(target.read_bytes(), b"")

    def test_exception_mid_stream_propagates_and_leaves_no_files(self):
        error = ConnectionError("connection reset")
        response = StreamingResponse([b"partial"], stream_exc=error)
        target = self.root / "file.txt"

        with self.assertRaises(ConnectionError) as ctx:
            _write(response, target)

        self.assertIs(ctx.exception, error)
        self.assertEqual(_tree(self.root), [])
        self.assertTrue(response.closed)

    def test_chunk_size_is_passed_to_iter_content(self):
        response = StreamingResponse([b"abc"])

        _write(response, self.root / "file.txt", chunk_size=7)

        self.assertEqual(response.chunk_sizes, [7])

    def test_default_chunk_size_is_one_mebibyte(self):
        response = StreamingResponse([b"abc"])

        _write(response, self.root / "file.txt")

        self.assertEqual(response.chunk_sizes, [1024 * 1024])

    def test_accepts_str_path(self):
        response = StreamingResponse([b"abc"])
        target = self.root / "file.txt"

        result = write_response_to_path(cast(Any, response), str(target))

        self.assertIsInstance(result, Path)
        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), b"abc")

    def test_invalid_path_raises_and_closes_response(self):
        response = StreamingResponse([b"abc"])

        with self.assertRaises(TypeError):
            write_response_to_path(cast(Any, response), cast(Any, None))

        self.assertTrue(response.closed)
        self.assertEqual(response.chunk_sizes, [])

    def test_long_target_name_downloads_without_leftovers(self):
        name = "n" * 246 + ".bin"
        self.assertEqual(len(name), 250)

        response = StreamingResponse([b"abc"])
        result = _write(response, self.root / name, md5=MD5_ABC, size=3)

        self.assertEqual(result, self.root / name)
        self.assertEqual((self.root / name).read_bytes(), b"abc")
        self.assertEqual(_tree(self.root), [name])

        failed = StreamingResponse([b"abc"])
        other = "m" * 246 + ".bin"
        with self.assertRaises(ValidationError):
            _write(failed, self.root / other, md5=MD5_HELLO_WORLD)

        self.assertEqual(_tree(self.root), [name])
        self.assertTrue(failed.closed)

    def _dangling_symlink(self, name: str) -> tuple[Path, Path]:
        link = self.root / name
        destination = self.root / "missing-destination"
        try:
            link.symlink_to(destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        return link, destination

    def test_dangling_symlink_target_counts_as_existing(self):
        link, destination = self._dangling_symlink("file.txt")
        response = StreamingResponse([b"abc"])

        with self.assertRaises(FileExistsError):
            _write(response, link)

        self.assertTrue(link.is_symlink())
        self.assertFalse(os.path.lexists(destination))
        self.assertEqual(_tree(self.root), ["file.txt"])
        self.assertTrue(response.closed)

    def test_overwrite_replaces_dangling_symlink_with_regular_file(self):
        link, destination = self._dangling_symlink("file.txt")
        response = StreamingResponse([b"abc"])

        result = _write(response, link, overwrite=True, md5=MD5_ABC, size=3)

        self.assertEqual(result, link)
        self.assertFalse(link.is_symlink())
        self.assertTrue(link.is_file())
        self.assertEqual(link.read_bytes(), b"abc")
        self.assertFalse(os.path.lexists(destination))
        self.assertEqual(_tree(self.root), ["file.txt"])


if __name__ == "__main__":
    unittest.main()
