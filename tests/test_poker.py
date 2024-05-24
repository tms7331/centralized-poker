import json
import pytest
import vanillapoker.poker as poker


@pytest.fixture
def t():
    return poker.PokerTable(1, 2, 40, 400, 6)


def test_join_table(t):
    # Join at a seat that is not 0
    assert t.seats[2] is None
    t.join_table(2, 100, "0x123")
    assert t.seats[2] is not None


def test_no_bad_join_tables(t):
    # Join at a seat that is not 0
    t.join_table(2, 100, "0x123")
    # Same player Joining at same or different seat should fail..
    with pytest.raises(AssertionError):
        t.join_table(2, 100, "0x123")
    with pytest.raises(AssertionError):
        t.join_table(0, 100, "0x123")
    # Different player joining at same seat should fail
    with pytest.raises(AssertionError):
        t.join_table(2, 100, "0x456")
    # Joining at an out of bounds index should fail
    with pytest.raises(AssertionError):
        t.join_table(-1, 100, "0x456")
    with pytest.raises(AssertionError):
        t.join_table(9, 100, "0x456")
    # Bad buying amount should fail
    with pytest.raises(AssertionError):
        t.join_table(1, 100000, "0x456")
    with pytest.raises(AssertionError):
        t.join_table(1, 1, "0x456")


def test_leave_table(t):
    t.join_table(0, 100, "0x123")
    assert t.seats[0] is not None
    t.leave_table(0, "0x123")
    assert t.seats[0] is None


def test_rebuy(t):
    t.join_table(0, 100, "0x123")
    # SHoudl be able to rebuy for max of 100 more
    t.rebuy(0, 100, "0x123")
    assert t.seats[0]["stack"] == 200
