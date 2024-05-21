import pytest
import poker


@pytest.fixture
def t():
    return poker.PokerTable(1, 2, 100, 200, 6)


def test_join_table(t):
    # Join at a seat that is not 0
    assert t.seats[2] is None
    t.join_table(2, 100, "0x123")
    assert t.seats[2] is not None


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
