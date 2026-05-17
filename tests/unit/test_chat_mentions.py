"""Tests for the @-mention plumbing in core/chat.py.

Covers:
- ``extract_mentions``: parser shape + dedup + ordering
- ``filter_mentions_to_members``: validation against a room member set
- ``mentions_gilbert``: legacy bare-name + structured-tag both detected
- ``conv_summary``: ``unread_mentions_count`` against a viewer's cursor
"""

from __future__ import annotations

from gilbert.core.chat import (
    GILBERT_MENTION_USER_ID,
    conv_summary,
    extract_mentions,
    filter_mentions_to_members,
    mentions_gilbert,
)

# --- extract_mentions ---


def test_extract_mentions_returns_user_ids_in_order() -> None:
    content = "hey @[Alice](alice-1) and @[Bob](bob-2), look at this"
    assert extract_mentions(content) == ["alice-1", "bob-2"]


def test_extract_mentions_dedupes_repeats_preserving_order() -> None:
    content = "@[Alice](alice) @[Bob](bob) @[Alice](alice) @[Carol](carol)"
    assert extract_mentions(content) == ["alice", "bob", "carol"]


def test_extract_mentions_handles_empty_string() -> None:
    assert extract_mentions("") == []
    assert extract_mentions(None) == []  # type: ignore[arg-type]


def test_extract_mentions_ignores_plain_at_text() -> None:
    # Legacy "@alice" without the bracket-link syntax isn't a
    # structured mention — extractor doesn't pick it up.
    assert extract_mentions("hey @alice come look") == []


def test_extract_mentions_rejects_unsafe_user_id_chars() -> None:
    # User id regex is ``[A-Za-z0-9._:-]+`` — spaces/parens break the
    # match, so a malicious tag like ``@[hi](rm -rf /)`` doesn't slip
    # an invalid id through.
    assert extract_mentions("@[hi](rm -rf /)") == []


def test_extract_mentions_allows_gilbert_pseudo_id() -> None:
    assert extract_mentions("@[Gilbert](gilbert) help") == [
        GILBERT_MENTION_USER_ID
    ]


# --- filter_mentions_to_members ---


def test_filter_drops_non_member_mentions() -> None:
    content = "@[Alice](alice) @[Eve](eve) @[Bob](bob)"
    members = {"alice", "bob"}
    valid, mentions_g = filter_mentions_to_members(content, members)
    assert valid == ["alice", "bob"]
    assert mentions_g is False


def test_filter_records_gilbert_separately() -> None:
    content = "@[Gilbert](gilbert) and @[Alice](alice) please"
    members = {"alice"}
    valid, mentions_g = filter_mentions_to_members(content, members)
    # Gilbert isn't a member — but he IS allowed through as a flag.
    assert valid == ["alice"]
    assert mentions_g is True


def test_filter_silent_when_no_mentions() -> None:
    valid, mentions_g = filter_mentions_to_members("plain text", {"alice"})
    assert valid == []
    assert mentions_g is False


# --- mentions_gilbert ---


def test_mentions_gilbert_legacy_bare_name() -> None:
    assert mentions_gilbert("gilbert, can you help?") is True
    assert mentions_gilbert("Gilbert please") is True
    assert mentions_gilbert("Hey Gilbert!") is True


def test_mentions_gilbert_structured_tag() -> None:
    assert mentions_gilbert("@[Gilbert](gilbert) help me out") is True


def test_mentions_gilbert_negative_cases() -> None:
    assert mentions_gilbert("not addressing the ai") is False
    # Word boundary — ``gilbertian`` shouldn't match. ``\bgilbert\b``
    # rejects this because the trailing alpha runs into the boundary.
    assert mentions_gilbert("the gilbertian school of thought") is False


# --- conv_summary unread_mentions_count ---


def _msg(
    *,
    role: str = "user",
    content: str = "",
    author_id: str = "",
    mentioned: list[str] | None = None,
) -> dict[str, object]:
    return {
        "role": role,
        "content": content,
        "author_id": author_id,
        "mentioned_user_ids": mentioned or [],
    }


def test_conv_summary_omits_unread_when_no_viewer() -> None:
    conv = {"_id": "c1", "messages": [_msg(mentioned=["alice"])], "members": []}
    out = conv_summary(conv, shared=True)
    assert "unread_mentions_count" not in out


def test_conv_summary_counts_unread_mentions_for_viewer() -> None:
    conv = {
        "_id": "c1",
        "messages": [
            _msg(author_id="bob", mentioned=["alice"]),
            _msg(author_id="bob", mentioned=["alice"]),
            _msg(author_id="bob", mentioned=["carol"]),
        ],
        "members": [
            {"user_id": "alice", "display_name": "Alice"},
            {"user_id": "bob", "display_name": "Bob"},
        ],
    }
    out = conv_summary(conv, shared=True, viewer_user_id="alice")
    assert out["unread_mentions_count"] == 2


def test_conv_summary_skips_messages_at_or_before_cursor() -> None:
    conv = {
        "_id": "c1",
        "messages": [
            _msg(author_id="bob", mentioned=["alice"]),  # idx 0 — seen
            _msg(author_id="bob", mentioned=["alice"]),  # idx 1 — seen
            _msg(author_id="bob", mentioned=["alice"]),  # idx 2 — unread
            _msg(author_id="bob", mentioned=["alice"]),  # idx 3 — unread
        ],
        "members": [
            {
                "user_id": "alice",
                "display_name": "Alice",
                "last_read_mention_index": 1,
            },
        ],
    }
    out = conv_summary(conv, shared=True, viewer_user_id="alice")
    assert out["unread_mentions_count"] == 2


def test_conv_summary_excludes_self_authored_mentions() -> None:
    # ``@-mention your own message'' shouldn't badge yourself.
    conv = {
        "_id": "c1",
        "messages": [
            _msg(author_id="alice", mentioned=["alice"]),
            _msg(author_id="bob", mentioned=["alice"]),
        ],
        "members": [{"user_id": "alice", "display_name": "Alice"}],
    }
    out = conv_summary(conv, shared=True, viewer_user_id="alice")
    assert out["unread_mentions_count"] == 1


def test_conv_summary_zero_when_viewer_is_not_mentioned() -> None:
    conv = {
        "_id": "c1",
        "messages": [_msg(author_id="bob", mentioned=["carol"])],
        "members": [{"user_id": "alice", "display_name": "Alice"}],
    }
    out = conv_summary(conv, shared=True, viewer_user_id="alice")
    assert out["unread_mentions_count"] == 0


def test_conv_summary_handles_missing_member_entry_for_viewer() -> None:
    # Viewer isn't a member — start cursor at -1 so every mention
    # counts as unread. (Realistic case: an admin browsing a public
    # room before joining.)
    conv = {
        "_id": "c1",
        "messages": [
            _msg(author_id="bob", mentioned=["alice"]),
            _msg(author_id="bob", mentioned=["alice"]),
        ],
        "members": [{"user_id": "bob", "display_name": "Bob"}],
    }
    out = conv_summary(conv, shared=True, viewer_user_id="alice")
    assert out["unread_mentions_count"] == 2


# --- Module-level constant accessibility ---


def test_gilbert_mention_user_id_constant() -> None:
    assert GILBERT_MENTION_USER_ID == "gilbert"
