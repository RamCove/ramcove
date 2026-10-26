"""King of the hill: the order of the five-king queue, read from a profile's champion history."""

from dataclasses import dataclass

from ramcove_protocol.weights import KING_SLOTS, select_kings


@dataclass(frozen=True)
class Rec:
    version: int
    submission_id: str | None
    author_hotkey: str | None
    status: str


def history(*authors: str) -> list[Rec]:
    """Version 0 is the tuned baseline; each author after it was crowned in turn by beating King #1."""
    recs = [Rec(0, None, None, "superseded" if authors else "current")]
    for v, author in enumerate(authors, start=1):
        recs.append(Rec(v, f"sub-{v}", author, "current" if v == len(authors) else "superseded"))
    return recs


def names(kings: list[Rec]) -> list[str | None]:
    return [k.author_hotkey for k in kings]


def test_only_the_baseline_means_no_king():
    assert select_kings(history(), current_version=0) == []


def test_beating_the_baseline_crowns_king_one():
    assert names(select_kings(history("A"), 1)) == ["A"]


def test_a_new_king_pushes_every_king_down_one_place():
    assert names(select_kings(history("A", "B", "C"), 3)) == ["C", "B", "A"]


def test_the_sixth_king_pushes_king_five_out_of_the_queue():
    recs = history("A", "B", "C", "D", "E", "F")
    assert KING_SLOTS == 5
    assert names(select_kings(recs, 6)) == ["F", "E", "D", "C", "B"]  # A is no longer paid


def test_a_rolled_back_king_leaves_the_queue_and_the_others_move_up():
    recs = history("A", "B", "C")
    recs[3] = Rec(3, "sub-3", "C", "rolled_back")
    # the rollback restores B's stack as a new version of the same submission
    recs[2] = Rec(2, "sub-2", "B", "superseded")
    recs.append(Rec(4, "sub-2", "B", "current"))
    assert names(select_kings(recs, 4)) == ["B", "A"]


def test_rolling_back_the_only_king_leaves_no_king():
    recs = [
        Rec(0, None, None, "superseded"),
        Rec(1, "sub-1", "A", "rolled_back"),
        Rec(2, None, None, "current"),
    ]
    assert select_kings(recs, 2) == []


def test_a_suspended_king_one_keeps_its_place():
    recs = history("A", "B")
    recs[2] = Rec(2, "sub-2", "B", "suspended")
    assert names(select_kings(recs, 2)) == ["B", "A"]


def test_one_author_can_hold_two_places_with_two_crowned_stacks():
    assert names(select_kings(history("A", "B", "A"), 3)) == ["A", "B", "A"]
