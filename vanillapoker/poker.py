import copy
import random
from functools import reduce
from enum import Enum
from typing import List, Tuple
from dataclasses import dataclass
from typing import Optional


# First 13 prime numbers
# Multiply them together to get a unique value, which we can use to
# evaluate hand strength using a lookup table
prime_mapping = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


class HandStage(Enum):
    SB_POST_STAGE = 0
    BB_POST_STAGE = 1
    HOLECARDS_DEAL = 2
    PREFLOP_BETTING = 3
    FLOP_DEAL = 4
    FLOP_BETTING = 5
    TURN_DEAL = 6
    TURN_BETTING = 7
    RIVER_DEAL = 8
    RIVER_BETTING = 9
    SHOWDOWN = 10
    SETTLE = 11


class ActionType(Enum):
    SB_POST = 0
    BB_POST = 1
    BET = 2
    FOLD = 3
    CALL = 4
    CHECK = 5


@dataclass
class HandState:
    player_stack: int
    player_bet_street: int
    whose_turn: int
    hand_stage: HandStage
    last_action_type: ActionType
    last_action_amount: int
    pot: int
    transition_next_street: bool
    closing_action_count: int
    facing_bet: int
    last_raise: int
    button: int


class PokerTable:
    """
    Class containing state for an individual poker table
    All game actions will modify this class
    """

    # Global hand_id - should be unique across all tables
    hand_id = 1
    lookup_table_basic_7c = {}

    def __init__(
        self,
        small_blind: int,
        big_blind: int,
        min_buyin: int,
        max_buyin: int,
        num_seats: int,
    ):
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.min_buyin = min_buyin
        self.max_buyin = max_buyin
        self.num_seats = num_seats

        # Should these contain empty player objects instead?
        self.seats = [None for _ in range(num_seats)]
        self.player_to_seat = {}

        self.hand_stage = HandStage.PREFLOP_BETTING
        self.pot = 0
        self.button = 0
        self.whose_turn = 0
        self.closing_action_count = 0
        self.facing_bet = 0
        self.last_raise = 0
        self.last_action_type = None
        self.last_action_amount = 0

        self.deck = list(range(52))
        random.shuffle(self.deck)
        self.board = []
        # We'll pop from this array in the api
        self.events = []

    @classmethod
    def set_lookup_table_basic_7c(cls, lookup_table_basic_7c):
        cls.lookup_table_basic_7c = lookup_table_basic_7c

    @classmethod
    def increment_hand_id(cls):
        cls.hand_id += 1

    def join_table_next_seat_i(self, deposit_amount: int, address: str):
        """
        Helper function to add player to next available seat
        """
        for seat_i, player in enumerate(self.seats):
            if player is None:
                self.join_table(seat_i, deposit_amount, address)
                break

    def join_table(self, seat_i: int, deposit_amount: int, address: str):
        """
        address should be a unique identifier for that player
        """
        assert self.seats[seat_i] == None, "seat_i taken!"
        assert address not in self.player_to_seat, "Player already joined!"
        assert (
            self.min_buyin <= deposit_amount <= self.max_buyin
        ), "Invalid deposit amount!"
        self.seats[seat_i] = {
            "address": address,
            "stack": deposit_amount,
            "in_hand": True,
            "auto_post": False,
            "sitting_out": False,
            "bet_street": 0,
            "showdown_val": 8000,
            "holecards": [],
            "last_action_type": None,
            "last_amount": None,
        }
        self.player_to_seat[address] = seat_i

        self.events.append(
            {
                "tag": "rebuy",
                "player": address,
                "seat": seat_i,
                "deposit_amount": deposit_amount,
            }
        )

    def leave_table(self, seat_i: int, address: str):
        assert self.seats[seat_i]["address"] == address, "Player not at seat!"
        self.seats[seat_i] = None
        self.player_to_seat.pop(address)
        self.events.append({"tag": "leaveTable", "player": address, "seat": seat_i})

    def rebuy(self, seat_i: int, rebuy_amount: int, address: str):
        assert self.seats[seat_i]["address"] == address, "Player not at seat!"
        new_stack = self.seats[seat_i]["stack"] + rebuy_amount
        assert self.min_buyin <= new_stack <= self.max_buyin, "Invalid rebuy amount"
        self.seats[seat_i]["stack"] = new_stack

        self.events.append(
            {
                "tag": "rebuy",
                "player": address,
                "seat": seat_i,
                "rebuy_amount": rebuy_amount,
            }
        )

    @staticmethod
    def _transition_hand_state(
        hs: HandState, action_type: ActionType, amount: int, num_players: int
    ) -> HandState:

        # Do we really need to copy this?
        hs_new = copy.deepcopy(hs)

        if action_type == ActionType.SB_POST:
            hs_new.hand_stage = ActionType.BB_POST
            hs_new.pot += amount
            hs_new.facing_bet = amount
            hs_new.last_raise = amount
            hs_new.whose_turn = 1 - hs.whose_turn
            hs_new.player_stack -= amount
            hs_new.player_bet_street = amount
        elif action_type == ActionType.BB_POST:
            hs_new.hand_stage = HandStage.HOLECARDS_DEAL
            hs_new.pot += amount
            hs_new.facing_bet = amount
            hs_new.last_raise = amount
            hs_new.whose_turn = 1 - hs.whose_turn
            hs_new.player_stack -= amount
            hs_new.player_bet_street = amount
        elif action_type == ActionType.BET:
            bet_amount_new = amount - hs.player_bet_street
            hs_new.player_stack -= bet_amount_new
            hs_new.player_bet_street = amount
            hs_new.pot += bet_amount_new
            hs_new.facing_bet = amount
            hs_new.last_raise = hs.player_bet_street - hs.facing_bet
            hs_new.closing_action_count = 1
            hs_new.whose_turn = 1 - hs.whose_turn
        elif action_type == ActionType.FOLD:
            # Only for two players!  Needs more work...
            hs_new.hand_stage = HandStage.SHOWDOWN
            hs_new.in_hand = False
            hs_new.betting_over = True
            hs_new.closing_action_count += 1
        elif action_type == ActionType.CALL:
            call_amount_new = hs.facing_bet - hs.player_bet_street
            hs_new.pot += call_amount_new
            hs_new.player_stack -= call_amount_new
            # TODO
            # hardcoded for 2 players, and we need to consider empty seats...
            hs_new.whose_turn = (hs.whose_turn + 1) % 2
            hs_new.player_bet_street += call_amount_new
            hs_new.closing_action_count += 1
        elif action_type == ActionType.CHECK:
            hs_new.closing_action_count += 1
            hs_new.whose_turn = (hs.whose_turn + 1) % 2

        hs_new.last_action_type = action_type
        hs_new.last_action_amount = amount

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

        return hs_new

    def _deal_holecards(self):
        """
        Keep first 5 cards for boardcards, deal from after that?
        """
        for seat_i in range(self.num_seats):
            if self.seats[seat_i]:
                start_i = 5 + seat_i * 2
                cards = self.deck[start_i : start_i + 2]
                self.seats[seat_i]["holecards"] = cards
                self.events.append(
                    {"tag": "cards", "card_type": f"p{seat_i}", "cards": cards}
                )

    def _deal_boardcards(self):
        if self.hand_stage == HandStage.FLOP_DEAL:
            self.board = self.deck[0:3]
            self.events.append(
                {"tag": "cards", "card_type": "flop", "cards": self.deck[0:3]}
            )
        elif self.hand_stage == HandStage.TURN_DEAL:
            self.board = self.deck[:4]
            self.events.append(
                {"tag": "cards", "card_type": "turn", "cards": self.deck[3:4]}
            )
        elif self.hand_stage == HandStage.RIVER_DEAL:
            self.board = self.deck[:5]
            self.events.append(
                {"tag": "cards", "card_type": "river", "cards": self.deck[4:5]}
            )

    def take_action(self, action_type: ActionType, address: str, amount: int):
        seat_i = self.player_to_seat[address]
        assert seat_i == self.whose_turn, "Not player's turn!"

        # Make sure it's their turn to act and they're in the hand?
        player_data = self.seats[seat_i]
        assert player_data["in_hand"], "Player not in hand!"

        # last_action = None if not self.events else self.events[-1]

        hs = HandState(
            player_stack=player_data["stack"],
            player_bet_street=player_data["bet_street"],
            whose_turn=self.whose_turn,
            hand_stage=self.hand_stage,
            last_action_type=self.last_action_type,
            last_action_amount=self.last_action_amount,
            pot=self.pot,
            transition_next_street=False,
            closing_action_count=self.closing_action_count,
            facing_bet=self.facing_bet,
            last_raise=self.last_raise,
            button=self.button,
        )

        # We actually need num players active on this street
        num_players = sum([1 for player in self.seats if player is not None])
        hs_new = self._transition_hand_state(hs, action_type, amount, num_players)

        # At this stage we might need to:
        # Deal cards
        # Showdown
        # Settle pot

        # And finally we'll want to update hand state

        next_hand = False
        if hs_new.hand_stage == HandStage.HOLECARDS_DEAL:
            self._deal_holecards()
            hs_new.hand_stage = HandStage.PREFLOP_BETTING
        elif hs_new.hand_stage == HandStage.FLOP_DEAL:
            self._deal_boardcards()
            hs_new.hand_stage = HandStage.FLOP_BETTING
        elif hs_new.hand_stage == HandStage.TURN_DEAL:
            self._deal_boardcards()
            hs_new.hand_stage = HandStage.TURN_BETTING
        elif hs_new.hand_stage == HandStage.RIVER_DEAL:
            self._deal_boardcards()
            hs_new.hand_stage = HandStage.RIVER_BETTING
        elif hs_new.hand_stage == HandStage.SHOWDOWN:
            self._showdown()
            self._settle()
            # Increment to next hand...
            # self._next_hand()
            next_hand = True
        elif hs_new.hand_stage == HandStage.SETTLE:
            hs_new.hand_stage = HandStage.RIVER_BETTING
            self._settle()
            # Increment to next hand...
            self._next_hand()
            next_hand = True

        # And now update state...
        self.seats[seat_i]["stack"] = hs_new.player_stack
        self.seats[seat_i]["bet_street"] = hs_new.player_bet_street
        self.seats[seat_i]["last_action_type"] = action_type.value
        self.seats[seat_i]["last_amount"] = amount

        self.whose_turn = hs_new.whose_turn
        self.hand_stage = hs_new.hand_stage
        self.last_action_type = hs_new.last_action_type
        self.last_action_amount = hs_new.last_action_amount
        self.pot = self.pot
        self.closing_action_count = hs_new.closing_action_count
        self.facing_bet = hs_new.facing_bet
        self.last_raise = hs_new.last_raise
        self.button = hs_new.button

        # TODO - make sure we don't call next_street if we've called next_hand?
        # Is it even possible?  Add an assertion?
        if hs_new.transition_next_street:
            self._next_street()

        # TODO -
        # we'll clear out events when we transition to nex<t hand
        # -so how do we cleanly access any final event in API?
        action = {
            "tag": "gameState",
            "pot": self.pot,
            "stackP0": self.seats[0]["stack"],
            "stackP1": self.seats[1]["stack"],
            "playerBetStreetP0": self.seats[0]["bet_street"],
            "playerBetStreetP1": self.seats[1]["bet_street"],
            "button": self.button,
            # And info about actual action that was taken?
            "action_type": action_type.value,
            "amount": amount,
            "address": address,
        }
        self.events.append(action)

        if next_hand:
            self._next_hand()

    def _settle(self):
        """
        At this point every player should have a "sd_value" set for their hands
        Evaluate whose is the LOWEST, and they win the pot
        """
        # what about split pots?
        winner_val = 0
        winner_i = []
        for seat_i, player in enumerate(self.seats):
            if player is not None:
                if player["showdown_val"] < winner_val:
                    winner_val = player["showdown_val"]
                    winner_i = [seat_i]
                elif player["showdown_val"] == winner_val:
                    winner_i.append(seat_i)

        num_winners = len(winner_i)
        for seat_i in winner_i:
            # TODO - can we have floating point errors here?  Should we round?
            self.seats[seat_i]["stack"] += self.pot / num_winners

    def _get_showdown_val(self, holecards, boardcards):
        """
        Showdown value
        """
        cards = holecards + boardcards
        assert len(cards) == 7
        # First get non-flush lookup value
        primes = [prime_mapping[x % 13] for x in cards]
        lookup_val = reduce(lambda x, y: x * y, primes)
        # Check for a flush too...

        return lookup_val

    def _showdown(self):
        """
        This will only be called if we get to showdown
        For all players still in the hand, calculate their showdown value and store it
        """
        for player in self.seats:
            if player is not None and player["in_hand"]:
                player["showdown_val"] = self._get_showdown_val([], [])

    def _next_street(self):
        # TODO - this is hardcoded for 2p
        self.whose_turn = self.button
        self.facing_bet = 0
        self.last_raise = 0
        self.last_action_type = None
        self.last_action_amount = 0

        # Reset player actions
        for player in self.seats:
            if player is not None:
                player["last_action_type"] = None
                player["last_amount"] = None

    def _next_hand(self):
        self.hand_stage = HandStage.PREFLOP_BETTING
        self.pot = 0
        self.button = (self.button + 1) % self.num_seats
        self.whose_turn = (self.whose_turn + 1) % self.num_seats
        self.closing_action_count = 0
        self.facing_bet = 0
        self.last_raise = 0
        self.last_action_type = None
        self.last_action_amount = 0

        self.deck = list(range(52))

        random.shuffle(self.deck)

        self.increment_hand_id()

        # And set all player sd values to highest value
        for seat_i in range(self.num_seats):
            if self.seats[seat_i]:
                self.seats[seat_i]["in_hand"] = True
                self.seats[seat_i]["bet_street"] = 0
                self.seats[seat_i]["showdown_val"] = 8000
                self.seats[seat_i]["holecards"] = []
