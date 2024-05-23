import json
import itertools
import copy
import random
from functools import reduce
from enum import Enum
from typing import List, Tuple
from dataclasses import dataclass
from typing import Optional
from vanillapoker import pokerutils


# First 13 prime numbers
# Multiply them together to get a unique value, which we can use to
# evaluate hand strength using a lookup table
prime_mapping = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


# class HandStage(Enum):
# Make them ints to simplify serialization
HS_SB_POST_STAGE = 0
HS_BB_POST_STAGE = 1
HS_HOLECARDS_DEAL = 2
HS_PREFLOP_BETTING = 3
HS_FLOP_DEAL = 4
HS_FLOP_BETTING = 5
HS_TURN_DEAL = 6
HS_TURN_BETTING = 7
HS_RIVER_DEAL = 8
HS_RIVER_BETTING = 9
HS_SHOWDOWN = 10
HS_SETTLE = 11


# class ActionType(Enum):
ACT_SB_POST = 0
ACT_BB_POST = 1
ACT_BET = 2
ACT_FOLD = 3
ACT_CALL = 4
ACT_CHECK = 5


@dataclass
class HandState:
    player_stack: int
    player_bet_street: int
    hand_stage: int  # HandStage
    last_action_type: int  # ActionType
    last_action_amount: int
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
    lookup_table_flush_5c = {}

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

        self.hand_stage = HS_SB_POST_STAGE
        # Pot up to this point in the hand
        self.pot_initial = 0
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

    @property
    def pot_total(self):
        """
        Pot including all bets on current street
        """
        bet_street = sum([x["bet_street"] for x in self.seats if x is not None])
        return self.pot_initial + bet_street

    @property
    def num_active_players(self):
        return sum(
            [1 for player in self.seats if player is not None and player["in_hand"]]
        )

    def serialize(self):
        """
        Store full game state in a way that we can stash it in a mysql table
        """
        return json.dumps(self.__dict__)

    def deserialize(self, dat):
        self.__dict__ = json.loads(dat)

    @classmethod
    def set_lookup_tables(cls, lookup_table_basic_7c, lookup_table_flush_5c):
        cls.lookup_table_basic_7c = lookup_table_basic_7c
        cls.lookup_table_flush_5c = lookup_table_flush_5c

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

    def leave_table_no_seat_i(self, address: str):
        for seat_i, player in enumerate(self.seats):
            if player["address"] == address:
                self.leave_table(seat_i, address)
                return
        raise Exception("Player not in game!")

    def rebuy_no_seat_i(self, rebuy_amount: int, address: str):
        for seat_i, player in enumerate(self.seats):
            if player["address"] == address:
                self.rebuy(seat_i, rebuy_amount, address)
                return
        raise Exception("Player not in game!")

    def join_table(
        self, seat_i: int, deposit_amount: int, address: str, auto_post=True
    ):
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
            "auto_post": auto_post,
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
                "tag": "joinTable",
                "player": address,
                "seat": seat_i,
                "depositAmount": deposit_amount,
            }
        )
        # If they're the FIRST player to join - give them the button and whose_turn?
        if sum([1 for player in self.seats if player is not None]) == 1:
            self.button = seat_i
            self.whose_turn = seat_i

        # If we hit two active players, we can start the hand
        self._handle_auto_post()

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
                "rebuyAmount": rebuy_amount,
            }
        )

    @staticmethod
    def _transition_hand_state(
        hs: HandState, action_type: int, amount: int
    ) -> HandState:
        # Do we really need to copy this?
        hs_new = copy.deepcopy(hs)

        if action_type == ACT_SB_POST:
            hs_new.hand_stage = ACT_BB_POST
            hs_new.facing_bet = amount
            hs_new.last_raise = amount
            hs_new.player_stack -= amount
            hs_new.player_bet_street = amount
        elif action_type == ACT_BB_POST:
            hs_new.hand_stage = HS_HOLECARDS_DEAL
            hs_new.facing_bet = amount
            hs_new.last_raise = amount
            hs_new.player_stack -= amount
            hs_new.player_bet_street = amount
        elif action_type == ACT_BET:
            bet_amount_new = amount - hs.player_bet_street
            hs_new.player_stack -= bet_amount_new
            hs_new.player_bet_street = amount
            hs_new.facing_bet = amount
            hs_new.last_raise = hs.player_bet_street - hs.facing_bet
            # For bets it reopens action
            hs_new.closing_action_count = 1
        elif action_type == ACT_FOLD:
            pass
        elif action_type == ACT_CALL:
            call_amount_new = hs.facing_bet - hs.player_bet_street
            hs_new.player_stack -= call_amount_new
            hs_new.player_bet_street += call_amount_new
            hs_new.closing_action_count += 1
        elif action_type == ACT_CHECK:
            hs_new.closing_action_count += 1

        hs_new.last_action_type = action_type
        hs_new.last_action_amount = amount

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
                    {"tag": "cards", "cardType": f"p{seat_i}", "cards": cards}
                )

    def _deal_boardcards(self, hs_new_hand_stage):
        if hs_new_hand_stage == HS_FLOP_DEAL:
            self.board = self.deck[0:3]
            self.events.append(
                {"tag": "cards", "cardType": "flop", "cards": self.deck[0:3]}
            )
        elif hs_new_hand_stage == HS_TURN_DEAL:
            self.board = self.deck[:4]
            self.events.append(
                {"tag": "cards", "cardType": "turn", "cards": self.deck[3:4]}
            )
        elif hs_new_hand_stage == HS_RIVER_DEAL:
            self.board = self.deck[:5]
            self.events.append(
                {"tag": "cards", "cardType": "river", "cards": self.deck[4:5]}
            )
        else:
            raise ValueError("Invalid hand stage")

    def take_action(self, action_type: int, address: str, amount: int):
        seat_i = self.player_to_seat[address]
        assert seat_i == self.whose_turn, "Not player's turn!"

        # Make sure it's their turn to act and they're in the hand?
        player_data = self.seats[seat_i]
        assert player_data["in_hand"], "Player not in hand!"

        # last_action = None if not self.events else self.events[-1]

        hs = HandState(
            player_stack=player_data["stack"],
            player_bet_street=player_data["bet_street"],
            hand_stage=self.hand_stage,
            last_action_type=self.last_action_type,
            last_action_amount=self.last_action_amount,
            transition_next_street=False,
            closing_action_count=self.closing_action_count,
            facing_bet=self.facing_bet,
            last_raise=self.last_raise,
            button=self.button,
        )

        hs_new = self._transition_hand_state(hs, action_type, amount)

        # If they fold - they're no longer in the hand
        if action_type == ACT_FOLD:
            self.seats[seat_i]["in_hand"] = False

        street_over = hs_new.closing_action_count == self.num_active_players
        if street_over:
            self.pot_initial = self.pot_total
            if hs.hand_stage == HS_PREFLOP_BETTING:
                hs_new.hand_stage = HS_FLOP_DEAL
            elif hs.hand_stage == HS_FLOP_BETTING:
                hs_new.hand_stage = HS_TURN_DEAL
            elif hs.hand_stage == HS_TURN_BETTING:
                hs_new.hand_stage = HS_RIVER_DEAL
            elif hs.hand_stage == HS_RIVER_BETTING:
                hs_new.hand_stage = HS_SHOWDOWN
            hs_new.transition_next_street = True

        # Overwrite previous logic
        if self.num_active_players == 1:
            hs_new.hand_stage = HS_SHOWDOWN

        # At this stage we might need to:
        # Deal cards
        # Showdown
        # Settle pot

        # And finally we'll want to update hand state

        next_hand = False

        if hs_new.hand_stage == HS_HOLECARDS_DEAL:
            self._deal_holecards()
            hs_new.hand_stage += 1
        elif hs_new.hand_stage in [
            HS_FLOP_DEAL,
            HS_TURN_DEAL,
            HS_RIVER_DEAL,
        ]:
            self._deal_boardcards(hs_new.hand_stage)
            # This will increment to a BETTING stage
            hs_new.hand_stage += 1
        elif hs_new.hand_stage == HS_SHOWDOWN:
            self._showdown()
            self._settle()
            # Increment to next hand...
            # self._next_hand()
            next_hand = True
        elif hs_new.hand_stage == HS_SETTLE:
            hs_new.hand_stage = HS_RIVER_BETTING
            self._settle()
            # Increment to next hand...
            self._next_hand()
            next_hand = True

        # And now update state...
        self.seats[seat_i]["stack"] = hs_new.player_stack
        self.seats[seat_i]["bet_street"] = hs_new.player_bet_street
        self.seats[seat_i]["last_action_type"] = action_type
        self.seats[seat_i]["last_amount"] = amount

        self.hand_stage = hs_new.hand_stage
        self.last_action_type = hs_new.last_action_type
        self.last_action_amount = hs_new.last_action_amount
        # self.pot = self.pot
        self.closing_action_count = hs_new.closing_action_count
        self.facing_bet = hs_new.facing_bet
        self.last_raise = hs_new.last_raise
        self.button = hs_new.button

        # Only increment if we're not at showdown
        if not next_hand:
            self._increment_whose_turn()

        # TODO - make sure we don't call next_street if we've called next_hand?
        # Is it even possible?  Add an assertion?
        if hs_new.transition_next_street:
            self._next_street()

        # TODO -
        # we'll clear out events when we transition to nex<t hand
        # -so how do we cleanly access any final event in API?
        # stack_arr = [x["stack"] for x in self.seats if x is not None else None]
        players = [pokerutils.build_player_data(seat) for seat in self.seats]
        action = {
            "tag": "gameState",
            "potInitial": self.pot_initial,
            "pot": self.pot_total,
            "players": players,
            "button": self.button,
            "whoseTurn": self.whose_turn,
            "board": self.board,
            "handStage": self.hand_stage,
            "facingBet": self.facing_bet,
            "lastRaise": self.last_raise,
            "action": {
                "type": action_type,
                "amount": amount,
            },
        }
        self.events.append(action)

        if next_hand:
            self._next_hand()

    def _settle(self):
        """
        At this point every player should have a "sd_value" set for their hands
        Evaluate whose is the LOWEST, and they win the pot
        """
        # Hacking in action here...
        action = {"tag": "settle", "pots": []}

        # what about split pots?
        winner_val = 8000
        winner_i = []
        for seat_i, player in enumerate(self.seats):
            if player is not None:
                if player["showdown_val"] < winner_val:
                    winner_val = player["showdown_val"]
                    winner_i = [seat_i]
                elif player["showdown_val"] == winner_val:
                    winner_i.append(seat_i)

        pot_dict = {"potTotal": self.pot_total, "winners": {}}

        num_winners = len(winner_i)
        for seat_i in winner_i:
            # TODO - can we have floating point errors here?  Should we round?
            self.seats[seat_i]["stack"] += self.pot_total / num_winners
            pot_dict["winners"][seat_i] = self.pot_total / num_winners

        action["pots"].append(pot_dict)
        self.events.append(action)

    def _get_showdown_val(self, cards):
        """
        Showdown value
        """
        assert len(cards) == 7
        # First get non-flush lookup value
        primes = [prime_mapping[x % 13] for x in cards]
        hand_val = reduce(lambda x, y: x * y, primes)
        lookup_val = self.lookup_table_basic_7c[str(int(hand_val))]

        # Check for a flush too...
        for suit in range(4):
            matches = [prime_mapping[x % 13] for x in cards if x // 13 == suit]
            if len(matches) >= 5:
                # Can have different combinations of 5 cards
                combos = itertools.combinations(matches, 5)
                for c in combos:
                    hand_val = reduce(lambda x, y: x * y, c)
                    lookup_val_ = self.lookup_table_flush_5c[str(int(hand_val))]
                    lookup_val = min(lookup_val, lookup_val_)

        return lookup_val

    def _showdown(self):
        """
        This will only be called if we get to showdown
        For all players still in the hand, calculate their showdown value and store it
        """
        action = {"tag": "showdown", "cards": [], "handStrs": []}

        # If everyone else folded - no lookups!
        # Otherwise their showdown_vals should still be at 8000
        still_in_hand = [p for p in self.seats if p is not None and p["in_hand"]]
        if len(still_in_hand) == 1:
            # This will award full pot to them
            still_in_hand[0]["showdown_val"] = 0
        else:
            for player in self.seats:
                if player is not None and player["in_hand"]:
                    holecards = player["holecards"]
                    player["showdown_val"] = self._get_showdown_val(
                        holecards + self.board
                    )
                    action["cards"].append(player["holecards"])
                    action["handStrs"].append("Placeholder-Flush")
                else:
                    action["cards"].append([])
                    action["handStrs"].append("")

            # Only send showdown event if we had a real showdown
            self.events.append(action)

    def _next_street(self):
        # TODO - this is hardcoded for 2p
        self.whose_turn = self.button

        self.facing_bet = 0
        self.last_raise = 0
        self.last_action_type = None
        self.last_action_amount = 0
        self.closing_action_count = 0

        # Reset player actions
        for player in self.seats:
            if player is not None:
                player["last_action_type"] = None
                player["last_amount"] = None
                player["bet_street"] = 0

    def _next_hand(self):
        self.hand_stage = HS_SB_POST_STAGE
        self.pot_initial = 0

        self.closing_action_count = 0
        self.facing_bet = 0
        self.last_raise = 0
        self.last_action_type = None
        self.last_action_amount = 0
        self.board = []

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

        self._increment_button()
        self.whose_turn = self.button
        self._handle_auto_post()

    def _handle_auto_post(self):
        # If we have two active players and game is in preflop stage - Post!
        if (
            self.hand_stage == HS_SB_POST_STAGE
            and len([p for p in self.seats if p is not None]) >= 2
        ):
            if self.seats[self.whose_turn]["auto_post"]:
                address_sb = self.seats[self.whose_turn]["address"]
                self.take_action(ACT_SB_POST, address_sb, self.small_blind)
                # whose_turn should have been incremented
                if self.seats[self.whose_turn]["auto_post"]:
                    address_bb = self.seats[self.whose_turn]["address"]
                    self.take_action(ACT_BB_POST, address_bb, self.big_blind)

    def _increment_button(self):
        """
        Should always progress to the next active player
        """
        # Sanity check - don't call it if there's only one player left
        active_players = sum(
            [
                not self.seats[i].get("sitting_out", True)
                for i in range(self.num_seats)
                if self.seats[i] is not None
            ]
        )

        # TODO - how do we handle moving button if there are players sitting out?
        # What if there are empty seats?
        if active_players >= 2:
            while True:
                self.button = (self.button + 1) % self.num_seats
                if self.seats[self.button] is None:
                    continue
                if self.seats[self.button].get("in_hand", False):
                    break

    def _increment_whose_turn(self):
        """
        Should always progress to the next active player
        """
        # Sanity check - don't call it if there's only one player left
        assert (
            sum(
                [
                    self.seats[i].get("in_hand", False)
                    for i in range(self.num_seats)
                    if self.seats[i] is not None
                ]
            )
            >= 2
        )
        while True:
            self.whose_turn = (self.whose_turn + 1) % self.num_seats
            if self.seats[self.whose_turn] is None:
                continue
            if self.seats[self.whose_turn].get("in_hand", False):
                break
