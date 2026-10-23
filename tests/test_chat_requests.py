import os
import pathlib
import json
import pytest
import time

from modules.chat_requests import (
    append_request,
    read_requests,
    DEFAULT_REQUEST_FILE,
)

# Helper to create a temporary file path
@pytest.fixture
def tmp_requests(tmp_path):
    path = tmp_path / "requests.jsonl"
    return path

# Test that a request is appended and read back correctly
def test_append_and_read(tmp_requests):
    # Append a well-formed request
    text = "Hello, world!"
    ok = append_request(tmp_requests, text)
    assert ok

    # Read starting from offset 0
    msgs, offset = read_requests(tmp_requests, 0)
    assert msgs == [text]
    # Next read should be empty
    msgs2, off2 = read_requests(tmp_requests, offset)
    assert msgs2 == []
    assert off2 == offset

# Test that append_request ignores empty or whitespace only strings
def test_append_empty(tmp_requests):
    assert append_request(tmp_requests, "") == False
    assert append_request(tmp_requests, "   ") == False

# Test that a partial line (no trailing newline) is ignored
def test_partial_line(tmp_requests):
    # Write a partial line without newline
    payload = {"at": 123456, "text": "partial"}
    with tmp_requests.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))  # no newline
    msgs, _ = read_requests(tmp_requests, 0)
    assert msgs == []

# Test that if file is truncated/rotated the offset resets

def test_truncate_reset(tmp_requests):
    # Append two lines
    assert append_request(tmp_requests, "first")
    assert append_request(tmp_requests, "second")
    # Record current size
    size1 = tmp_requests.stat().st_size
    # Now truncate to smaller size (zero)
    with tmp_requests.open("wb") as f:
        f.truncate(0)
    # reading with offset beyond size should reset offset
    msgs, offset = read_requests(tmp_requests, size1)
    # Since file truncated, should read all again
    assert msgs == []
    assert offset == 0



@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_complete_record_followed_by_partial_unicode_record(tmp_requests, newline):
    first = json.dumps({'text': 'first café'}, ensure_ascii=False).encode() + newline
    second = json.dumps({'text': 'second 😀'}, ensure_ascii=False).encode() + newline
    split = second.index('😀'.encode()) + 2
    tmp_requests.write_bytes(first + second[:split])
    messages, offset = read_requests(tmp_requests)
    assert messages == ['first café'] and offset == len(first)
    with tmp_requests.open('ab') as stream:
        stream.write(second[split:])
    messages, offset = read_requests(tmp_requests, offset)
    assert messages == ['second 😀'] and offset == len(first + second)
    assert read_requests(tmp_requests, offset) == ([], offset)


def test_malformed_utf8_does_not_shift_following_record_offset(tmp_requests):
    first = b'{"text":"bad \xff byte"}\r\n'
    tmp_requests.write_bytes(first)
    _, offset = read_requests(tmp_requests)
    assert offset == len(first)
    with tmp_requests.open('ab') as stream:
        stream.write(b'{"text":"next"}\n')
    assert read_requests(tmp_requests, offset)[0] == ['next']
