"""Bounded in-memory log-tail signatures; never persist or return raw logs."""

import hashlib
import io
import json
import re
import stat
import uuid
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024
MAX_FILES = 100
TAIL_LINES = 40
ALGORITHM = "log-tail-v1"

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
_PATH = re.compile(r"(?<![\w:])(?:[A-Za-z]:[\\/]|/)[^\s\x00<>\"']+")
_PID = re.compile(r"\b(pid|process(?: id)?)\s*[:=#]?\s*\d+\b", re.IGNORECASE)


class LogSignatureError(Exception):
    """Invalid, unsupported, empty or oversized log archive; contains no payload."""


@dataclass(frozen=True)
class LogSignature:
    """Only content digest and algorithm metadata, never text or archive filenames."""

    digest: str
    file_count: int
    algorithm: str = ALGORITHM


def _tail(text: str) -> str:
    normalized = _ANSI.sub("", text)
    normalized = _TIMESTAMP.sub("<time>", normalized)
    normalized = _PATH.sub("<path>", normalized)
    normalized = _PID.sub("pid=<pid>", normalized)
    lines = [" ".join(line.split()) for line in normalized.splitlines() if line.strip()]
    return "\n".join(lines[-TAIL_LINES:])[-65536:]


def signature_from_archive(raw: bytes) -> LogSignature:
    """Hash bounded UTF-8 .txt log tails without extracting anything to disk.

    File order and duplicate per-file tails do not affect a signature. Ordinary
    numbers and error codes remain significant. Empty/unavailable logs do not
    fabricate a shared empty signature. Filenames are never part of the digest.
    """
    try:
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive limit")
        tails = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError("File count")
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                raise ValueError("Expanded limit")
            seen = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or bool(re.match(r"^[A-Za-z]:", entry.filename))
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or entry.filename in seen
                    or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                ):
                    raise ValueError("Unsafe entry")
                seen.add(entry.filename)
                if entry.is_dir():
                    continue
                if path.suffix.lower() != ".txt":
                    raise ValueError("Unsupported log member")
                if entry.file_size > max(entry.compress_size, 1) * 100:
                    raise ValueError("Compression ratio")
                with archive.open(entry) as member:
                    data = member.read(min(entry.file_size, MAX_EXPANDED_BYTES) + 1)
                if len(data) != entry.file_size:
                    raise ValueError("Invalid member")
                tail = _tail(data.decode("utf-8-sig"))
                if tail:
                    tails.append(hashlib.sha256(tail.encode()).hexdigest())
        if not tails:
            raise ValueError("No usable logs")
        digest = hashlib.sha256(
            json.dumps([ALGORITHM, sorted(set(tails))], separators=(",", ":")).encode()
        ).hexdigest()
        return LogSignature(digest, len(tails))
    except (
        ValueError,
        OSError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        EOFError,
        OverflowError,
        zlib.error,
    ):
        raise LogSignatureError("Workflow log signature could not be computed") from None


def failure_fingerprint(
    org_id: uuid.UUID,
    repository_id: int,
    workflow_id: int,
    branch: str,
    signature: LogSignature,
) -> str:
    """Scope a normalized log digest; does not mutate incidents or observations."""
    if (
        type(repository_id) is not int
        or repository_id <= 0
        or type(workflow_id) is not int
        or workflow_id <= 0
        or not isinstance(branch, str)
        or not branch
        or len(branch) > 255
        or signature.algorithm != ALGORITHM
        or re.fullmatch(r"[0-9a-f]{64}", signature.digest) is None
    ):
        raise ValueError("Valid workflow scope and log signature required")
    return hashlib.sha256(
        json.dumps(
            [
                str(org_id),
                repository_id,
                workflow_id,
                branch,
                signature.algorithm,
                signature.digest,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
