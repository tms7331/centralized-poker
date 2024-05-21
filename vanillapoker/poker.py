import json
import requests
from enum import Enum
from typing import List, Tuple
from dataclasses import dataclass
from typing import Optional


class HandStage(Enum):
    PREFLOP_BETTING = 0
    FLOP_DEAL = 1
    FLOP_BETTING = 2
    TURN_DEAL = 3
    TURN_BETTING = 4
    RIVER_DEAL = 5
    RIVER_BETTING = 6
    SHOWDOWN = 7
    SETTLE = 8


class ActionType(Enum):
    SB_POST = 0
    BB_POST = 1
    BET = 2
    FOLD = 3
    CALL = 4
    CHECK = 5


@dataclass
class Action:
    amount: int
    act: ActionType


@dataclass
class HandState:
    handStage: HandStage
    lastAction: Action
    pot: int
    bettingOver: bool
    transitionNextStreet: bool
    closingActionCount: int
    facingBet: int
    lastRaise: int
    button: int


@dataclass
class PlayerState:
    whoseTurn: int
    stack: int
    inHand: bool
    playerBetStreet: int


class PokerTable:
    """
    Class containing state for an individual poker table
    All actions will modify this class
    """

    def __init__(self, small_blind, big_blind, min_buyin, max_buyin, num_seats):
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.min_buyin = min_buyin
        self.max_buyin = max_buyin
        self.num_seats = num_seats

        # Should these contain empty player objects instead?
        self.seats = [None for _ in range(num_seats)]
        self.hand_stage = HandStage.PREFLOP_BETTING

    def join_table_next_seat_i(self, deposit_amount, player_id):
        """
        Helper function to add player to next available seat
        """
        for seat_i, player in enumerate(self.seats):
            if player is None:
                self.join_table(seat_i, deposit_amount, player_id)
                break

    def join_table(self, seat_i, deposit_amount, player_id):
        """
        player_id should be a unique identifier for that player
        """
        assert self.seats[seat_i] == None, "seat_i taken!"
        assert (
            self.min_buyin <= deposit_amount <= self.max_buyin
        ), "Invalid deposit amount!"
        self.seats[seat_i] = {
            "player_id": player_id,
            "stack": deposit_amount,
            "in_hand": True,
            "auto_post": False,
            "sitting_out": False,
            "player_bet_street": 0,
        }

    def leave_table(self, seat_i, player_id):
        assert self.seats[seat_i]["player_id"] == player_id, "Player not at seat!"
        self.seats[seat_i] = None

    def rebuy(self, seat_i, rebuy_amount, player_id):
        assert self.seats[seat_i]["player_id"] == player_id, "Player not at seat!"
        new_stack = self.seats[seat_i]["stack"] + rebuy_amount
        assert self.min_buyin <= new_stack <= self.max_buyin, "Invalid rebuy amount"
        self.seats[seat_i]["stack"] = new_stack

    ####################3

    def _transition_hand_state(
        self, hs: HandState, ps: PlayerState, action: Action
    ) -> Tuple[HandState, PlayerState]:
        hs_new = hs
        ps_new = ps
        if action.act == ActionType.SB_POST:
            hs_new.hand_stage = HandStage.BB_POST
            hs_new.last_action = action
            hs_new.pot += action.amount
            hs_new.facing_bet = action.amount
            hs_new.last_raise = action.amount
            ps_new.whose_turn = 1 - ps.whose_turn
            ps_new.stack -= action.amount
            ps_new.player_bet_street = action.amount
        elif action.act == ActionType.BB_POST:
            hs_new.hand_stage = HandStage.HOLECARDS_DEAL
            hs_new.last_action = action
            hs_new.pot += action.amount
            hs_new.facing_bet = action.amount
            hs_new.last_raise = action.amount
            ps_new.whose_turn = 1 - ps.whose_turn
            ps_new.stack -= action.amount
            ps_new.player_bet_street = action.amount
        elif action.act == ActionType.BET:
            bet_amount_new = action.amount - ps.player_bet_street
            ps_new.stack -= bet_amount_new
            ps_new.player_bet_street = action.amount
            hs_new.last_action = action
            hs_new.pot += bet_amount_new
            hs_new.facing_bet = action.amount
            hs_new.last_raise = ps.player_bet_street - hs.facing_bet
            hs_new.closing_action_count = 1
            ps_new.whose_turn = 1 - ps.whose_turn
        elif action.act == ActionType.FOLD:
            hs_new.hand_stage = HandStage.SHOWDOWN
            hs_new.last_action = action
            ps_new.in_hand = False
            hs_new.betting_over = True
            hs_new.closing_action_count += 1
        elif action.act == ActionType.CALL:
            call_amount_new = hs.facing_bet - ps.player_bet_street
            hs_new.pot += call_amount_new
            ps_new.stack -= call_amount_new
            hs_new.last_action = action
            ps_new.whose_turn = (ps.whose_turn + 1) % 2
            ps_new.player_bet_street += call_amount_new
            hs_new.closing_action_count += 1
        elif action.act == ActionType.CHECK:
            hs_new.closing_action_count += 1
            ps_new.whose_turn = (ps.whose_turn + 1) % 2
            hs_new.last_action = action

        num_players = 2
        street_over = hs_new.closing_action_count == num_players
        if street_over:
            if hs.hand_stage == HandStage.PREFLOP_BETTING:
                hs_new.hand_stage = HandStage.FLOP_DEAL
            elif hs.hand_stage == HandStage.FLOP_BETTING:
                hs_new.hand_stage = HandStage.TURN_DEAL
            elif hs.hand_stage == HandStage.TURN_BETTING:
                hs_new.hand_stage = HandStage.RIVER_DEAL
            elif hs.hand_stage == HandStage.RIVER_BETTING:
                hs_new.hand_stage = HandStage.SHOWDOWN
            hs_new.transition_next_street = True

        if hs_new.hand_stage == HandStage.SHOWDOWN:
            hs_new.betting_over = True

        return hs_new, ps_new

    def take_action(self, action, player_id):
        if not self.init_complete:
            raise Exception("Table not initialized")
        player_seat_i = None
        for seat_i, player in self.players.items():
            if player["player_id"] == player_id:
                player_seat_i = seat_i
                break
        if player_seat_i is None:
            raise Exception("Player not found")
        hand_state = HandState()
        player_state = PlayerState()
        hand_state_new, player_state_new = self._transition_hand_state(
            hand_state, player_state, action
        )


##########################################
