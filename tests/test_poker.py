import json
import pytest
import vanillapoker.poker as poker


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


def test_transition_hand_state(t):
    hs = poker.HandState(
        player_stack=100,
        player_bet_street=23,
        whose_turn=0,
        hand_stage=poker.HS_FLOP_BETTING,
        last_action_type=poker.ACT_BET,
        last_action_amount=10,
        transition_next_street=False,
        closing_action_count=1,
        facing_bet=10,
        last_raise=10,
        button=0,
    )
    action_type = poker.ACT_CALL
    amount = 0

    t._transition_hand_state(hs, action_type, amount)
    # Add more checks for proper transition...
    assert True


def test_integration(t):
    """
    Play a full hand - both players join, play, then quit...
    """

    hs = poker.HandState(
        player_stack=100,
        player_bet_street=23,
        whose_turn=0,
        hand_stage=poker.HandStage.FLOP_BETTING,
        last_action_type=poker.ACT_BET,
        last_action_amount=10,
        transition_next_street=False,
        closing_action_count=1,
        facing_bet=10,
        last_raise=10,
        button=0,
    )
    action_type = poker.ACT_CALL
    amount = 0
    num_players = 2

    t._transition_hand_state(hs, action_type, amount)
    # Add more checks for proper transition...
    assert True


def test_get_showdown_val_basic(t):
    with open("handevaluator/lookup_table_flushes.json", "r") as f:
        lookup_table_flushes = json.loads(f.read())
    with open("handevaluator/lookup_table_basic_7c.json", "r") as f:
        lookup_table_basic_7c = json.loads(f.read())

    poker.PokerTable.set_lookup_tables(lookup_table_basic_7c, lookup_table_flushes)

    lookup_val_expected = 10
    aces_plus_king = [12, 12 + 13, 12 + 13 * 2, 12 + 13 * 3, 11]
    # Choose three other random cards
    cards = aces_plus_king + [0, 1]
    lookup_val = t._get_showdown_val(cards)
    assert lookup_val == lookup_val_expected


def test_get_showdown_val_flush(t):
    with open("handevaluator/lookup_table_flushes.json", "r") as f:
        lookup_table_flushes = json.loads(f.read())
    with open("handevaluator/lookup_table_basic_7c.json", "r") as f:
        lookup_table_basic_7c = json.loads(f.read())

    poker.PokerTable.set_lookup_tables(lookup_table_basic_7c, lookup_table_flushes)

    # Royal flush!
    lookup_val_expected = 0
    rf = [8, 9, 10, 11, 12]
    # Choose three other random cards
    cards = rf + [0, 1]
    lookup_val = t._get_showdown_val(cards)
    assert lookup_val == lookup_val_expected


def test_integration(t):
    """
    Play a full hand - both players join, play, then quit...
    """
    # Mock showdown to return same value always
    t._get_showdown_val = lambda x: 10
    p0 = "0x123"
    p1 = "0x456"
    t.join_table(0, 100, p0)
    t.join_table(1, 100, p1)

    # Preflop
    # t.take_action(poker.ACT_SB_POST, p0, 1)
    # t.take_action(poker.ACT_BB_POST, p1, 2)
    t.take_action(poker.ACT_CALL, p0, 0)
    t.take_action(poker.ACT_CHECK, p1, 0)
    assert len(t.board) == 3

    # Flop
    t.take_action(poker.ACT_BET, p0, 10)
    t.take_action(poker.ACT_CALL, p1, 0)

    # Turn
    t.take_action(poker.ACT_BET, p0, 10)
    t.take_action(poker.ACT_CALL, p1, 0)

    assert len(t.events) > 0

    # River
    t.take_action(poker.ACT_BET, p0, 10)
    t.take_action(poker.ACT_CALL, p1, 0)

    # No longer resetting!
    # assert len(t.events) == 0
    # assert False
