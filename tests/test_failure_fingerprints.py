"""Pure log signature tests with synthetic archives; no raw payload retention."""

import io
import stat
import uuid
import zipfile

import pytest

from svaar.incidents.fingerprints import (
    MAX_ARCHIVE_BYTES,
    LogSignatureError,
    failure_fingerprint,
    signature_from_archive,
)


def archive(files, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as handle:
        for name, value in files:
            handle.writestr(name, value)
    return buffer.getvalue()


def test_normalized_timestamps_paths_and_pids_keep_error_identity():
    a = archive(
        [
            (
                "job/1_test.txt",
                "2026-10-26T10:01:02.123Z ERROR /home/runner/work/a.py pid=123: exit 17",
            )
        ]
    )
    b = archive(
        [("renamed/99_test.txt", "2026-10-27T11:02:03.999Z ERROR C:\\work\\b.py pid=999: exit 17")]
    )
    first, second = signature_from_archive(a), signature_from_archive(b)
    assert first.digest == second.digest
    assert "runner" not in repr(first) and "ERROR" not in repr(first)
    different = archive([("job.txt", "2026-10-26T10:01:02.123Z ERROR /tmp/a.py pid=12: exit 18")])
    assert first.digest != signature_from_archive(different).digest


def test_file_order_does_not_change_digest_but_other_errors_do():
    a = [("a.txt", "compile error 7"), ("b.txt", "test error 4")]
    assert (
        signature_from_archive(archive(a)).digest == signature_from_archive(archive(a[::-1])).digest
    )
    assert (
        signature_from_archive(archive(a)).digest
        != signature_from_archive(
            archive([("a.txt", "compile error 8"), ("b.txt", "test error 4")])
        ).digest
    )


def test_only_tail_lines_affect_digest_and_ansi_is_removed():
    a = "earlier content\n" + "\n".join(f"error {i}" for i in range(40))
    b = "different earlier content\n" + "\n".join(f"\x1b[31merror {i}\x1b[0m" for i in range(40))
    assert (
        signature_from_archive(archive([("a.txt", a)])).digest
        == signature_from_archive(archive([("a.txt", b)])).digest
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"not-a-zip",
        archive([]),
        archive([("a.txt", " \n ")]),
        archive([("../escape.txt", "private")]),
        archive([("/absolute.txt", "private")]),
        archive([("dir\\escape.txt", "private")]),
        archive([("a.exe", "private")]),
        archive([("a.txt", b"\xff\xfe")]),
        archive([(f"{i}.txt", "error") for i in range(101)]),
        archive([("bomb.txt", "x" * 100000)], compression=zipfile.ZIP_DEFLATED),
        b"x" * (MAX_ARCHIVE_BYTES + 1),
    ],
)
def test_bad_or_oversized_logs_never_fabricate_signature(raw):
    with pytest.raises(LogSignatureError) as exc:
        signature_from_archive(raw)
    assert "private" not in str(exc.value)


def test_symlink_member_is_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as handle:
        entry = zipfile.ZipInfo("link.txt")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        handle.writestr(entry, "/private-target")
    with pytest.raises(LogSignatureError):
        signature_from_archive(stream.getvalue())


def test_scoped_fingerprint_never_groups_across_org_repo_workflow_branch():
    signature = signature_from_archive(archive([("job.txt", "error 17")]))
    org = uuid.uuid4()
    original = failure_fingerprint(org, 1, 2, "main", signature)
    for args in [
        (uuid.uuid4(), 1, 2, "main"),
        (org, 3, 2, "main"),
        (org, 1, 3, "main"),
        (org, 1, 2, "other"),
    ]:
        assert original != failure_fingerprint(*args, signature)
