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
        hand_stage=poker.HandStage.FLOP_BETTING,
        last_action_type=poker.ActionType.BET,
        last_action_amount=10,
        pot=20,
        transition_next_street=False,
        closing_action_count=1,
        facing_bet=10,
        last_raise=10,
        button=0,
    )
    action_type = poker.ActionType.CALL
    amount = 0
    num_players = 2

    t._transition_hand_state(hs, action_type, amount, num_players)
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
        last_action_type=poker.ActionType.BET,
        last_action_amount=10,
        pot=20,
        transition_next_street=False,
        closing_action_count=1,
        facing_bet=10,
        last_raise=10,
        button=0,
    )
    action_type = poker.ActionType.CALL
    amount = 0
    num_players = 2

    t._transition_hand_state(hs, action_type, amount, num_players)
    # Add more checks for proper transition...
    assert True


def test_integration(t):
    """
    Play a full hand - both players join, play, then quit...
    """
    at = poker.ActionType
    p0 = "0x123"
    p1 = "0x456"
    t.join_table(0, 100, p0)
    t.join_table(1, 100, p1)

    # Preflop
    t.take_action(at.SB_POST, p0, 1)
    t.take_action(at.BB_POST, p1, 2)
    t.take_action(at.CALL, p0, 0)
    t.take_action(at.CHECK, p1, 0)

    # Flop
    t.take_action(at.BET, p0, 10)
    t.take_action(at.CALL, p1, 0)

    # Turn
    t.take_action(at.BET, p0, 10)
    t.take_action(at.CALL, p1, 0)

    assert len(t.events) > 0

    # River
    t.take_action(at.BET, p0, 10)
    t.take_action(at.CALL, p1, 0)

    # Basic check to make sure we reset...
    assert len(t.events) == 0
