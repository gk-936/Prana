"""Tests for dates.reconstruct_block_dates — the 144-counter block date
reconstruction used for sites whose date strings are unreliable
(Faisalabad's mid-file DD-MM/MM-DD flip, Yavatmal's midnight-rollover dups)."""
import pandas as pd
import pytest

from research.indoor_heat.core.dates import reconstruct_block_dates, DateContinuityError


def _block(date_str, n):
    """One block: n rows all stamped date_str, counter 1..n."""
    return pd.DataFrame({"date": [date_str] * n, "ctr": list(range(1, n + 1))})


def test_assigns_sequential_dates_across_blocks():
    # Three clean blocks; reconstruction should yield 3 consecutive days
    # anchored on the first unambiguous block (15-03 = 15 March, DD-MM).
    df = pd.concat([_block("15-03-2016", 4), _block("16-03-2016", 4),
                    _block("17-03-2016", 4)], ignore_index=True)
    out = reconstruct_block_dates(df["date"], df["ctr"])
    days = out.dt.date.astype(str).unique().tolist()
    assert days == ["2016-03-15", "2016-03-16", "2016-03-17"]


def test_corrects_midnight_rollover_duplicate():
    # Middle block repeats the previous day's date (Yavatmal-style); the
    # counter still resets, so the block must be re-dated to anchor+1.
    df = pd.concat([_block("15-03-2016", 4), _block("15-03-2016", 4),
                    _block("17-03-2016", 4)], ignore_index=True)
    out = reconstruct_block_dates(df["date"], df["ctr"])
    days = out.dt.date.astype(str).unique().tolist()
    assert days == ["2016-03-15", "2016-03-16", "2016-03-17"]


def test_handles_convention_flip_between_blocks():
    # First block DD-MM (28-03 -> 28 March), next block flips to MM-DD
    # (03-29 -> 29 March). Sequence anchoring makes the second block
    # anchor+1 regardless of how its own string reads.
    df = pd.concat([_block("28-03-2016", 4), _block("03-29-2016", 4)],
                   ignore_index=True)
    out = reconstruct_block_dates(df["date"], df["ctr"])
    days = out.dt.date.astype(str).unique().tolist()
    assert days == ["2016-03-28", "2016-03-29"]


def test_detects_short_block_via_counter_drop():
    # A short first block (only 3 readings, counter 1..3) followed by a full
    # block. Reset must be detected from the counter DROP (3 -> 1), not from
    # "previous == 144", so the two days don't merge.
    short = pd.DataFrame({"date": ["15-03-2016"] * 3, "ctr": [1, 2, 3]})
    full = _block("16-03-2016", 4)
    df = pd.concat([short, full], ignore_index=True)
    out = reconstruct_block_dates(df["date"], df["ctr"])
    days = out.dt.date.astype(str).unique().tolist()
    assert days == ["2016-03-15", "2016-03-16"]


def test_raises_without_block_structure():
    # A single block (no reset) cannot establish sequence structure.
    df = _block("15-03-2016", 5)
    with pytest.raises(DateContinuityError):
        reconstruct_block_dates(df["date"], df["ctr"])


def test_anchors_on_first_unambiguous_block():
    # First block is ambiguous (05-06: could be May 6 or June 5); second
    # block is unambiguous DD-MM (07-06 -> wait, still ambiguous). Use a
    # clearly-unambiguous later block (15-06 = 15 June) to anchor, and
    # confirm the ambiguous first block is back-filled as anchor-1.
    df = pd.concat([_block("05-06-2016", 4), _block("15-06-2016", 4)],
                   ignore_index=True)
    # Second block (15-06) is unambiguous DD-MM -> 15 June; first block is
    # one day earlier by sequence = 14 June.
    out = reconstruct_block_dates(df["date"], df["ctr"])
    days = out.dt.date.astype(str).unique().tolist()
    assert days == ["2016-06-14", "2016-06-15"]
