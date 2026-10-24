"""Optional byte-identical export copies, without replacing user files."""
from __future__ import annotations

import errno
import hashlib
import os
import stat
import tempfile
from pathlib import Path


_CHUNK_SIZE = 1024 * 1024
_MAX_VERSION = 9999
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SYSTEM_ROOTS = tuple(Path(value) for value in ('/System', '/Library', '/Applications'))
_PNG = b'\x89PNG\r\n\x1a\n'


def _within(path, root):
    return path == root or root in path.parents


def _directory(value, source):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError('另存目录须为本机绝对路径或以 ~ 开头的路径')
    value = os.fspath(value)
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        raise ValueError('另存目录不能包含控制字符')
    try:
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError('另存目录须为本机绝对路径或以 ~ 开头的路径')
        path = path.resolve()
        roots = [_PROJECT_ROOT / 'data', _PROJECT_ROOT / 'output']
        # A packaged or migrated installation can keep its archive outside this
        # module's checkout. Reject that source archive as well.
        for ancestor in source.resolve().parents:
            if ancestor.name == 'output':
                roots.extend((ancestor, ancestor.parent / 'data'))
                break
        if path == Path(path.anchor) or any(_within(path, root) for root in _SYSTEM_ROOTS):
            raise ValueError('请选择个人文件夹作为另存目录')
        if any(_within(path, root.resolve()) for root in roots):
            raise ValueError('另存目录不能放在应用的 data 或 output 归档目录内')
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ValueError('另存目录不能指向现有文件')
        return path
    except (OSError, RuntimeError) as exc:
        raise ValueError('无法访问另存目录，请检查路径和文件夹权限') from exc


def _same_content(path, size, digest):
    """Compare only regular files, never following a destination symlink."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size != size:
            return False
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
            | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as existing:
            opened = os.fstat(existing.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                    or opened.st_size != size):
                return False
            result = hashlib.sha256()
            for block in iter(lambda: existing.read(_CHUNK_SIZE), b''):
                result.update(block)
            after = path.lstat()
            return (result.digest() == digest
                and (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns))
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ELOOP, errno.EISDIR, errno.EACCES, errno.EPERM):
            return False
        raise


def _version_name(source, version):
    if version == 1:
        return source.name
    ending = f'-版本{version:02d}{source.suffix}'
    # Leave room for the collision suffix even for an existing 255-byte name.
    stem = source.stem.encode('utf-8')[:255 - len(ending.encode('utf-8'))].decode('utf-8', 'ignore')
    return stem + ending


def copy_export(source, directory, *, draft_id, render_scale=1, sequence=1) -> Path | None:
    """Copy a named PNG to an optional local folder, preserving every old file.

    The renderer has already chosen its filename; draft, scale and sequence stay
    in the interface as render context and do not rename it a second time.
    """
    if directory is None or (isinstance(directory, str) and not directory.strip()):
        return None
    source = Path(source)
    target_directory = _directory(directory, source)
    temporary = None
    try:
        with source.open('rb') as original:
            before = os.fstat(original.fileno())
            if not stat.S_ISREG(before.st_mode) or source.suffix.lower() != '.png':
                raise ValueError('另存源文件须为导出的 PNG 图片')
            header = original.read(len(_PNG))
            if header != _PNG:
                raise ValueError('另存源文件须为导出的 PNG 图片')
            descriptor, name = tempfile.mkstemp(prefix='.discord-export-', suffix='.tmp', dir=target_directory)
            temporary = Path(name)
            digest = hashlib.sha256(header)
            size = len(header)
            with os.fdopen(descriptor, 'wb') as copied:
                copied.write(header)
                for block in iter(lambda: original.read(_CHUNK_SIZE), b''):
                    copied.write(block)
                    digest.update(block)
                    size += len(block)
                copied.flush()
                os.fsync(copied.fileno())
            after = os.fstat(original.fileno())
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or size != after.st_size):
                raise ValueError('图片在另存时发生变化，请重新导出后重试')
        for version in range(1, _MAX_VERSION + 1):
            target = target_directory / _version_name(source, version)
            try:
                # Same-directory hard links publish the completed bytes in one
                # step and fail exclusively if another writer claimed the name.
                os.link(temporary, target, follow_symlinks=False)
                return target
            except FileExistsError:
                if _same_content(target, size, digest.digest()):
                    return target
        raise ValueError('同名导出版本过多，请更换另存目录或文件名前缀')
    except OSError as exc:
        raise ValueError('无法另存图片，请检查目录权限和可用空间') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
