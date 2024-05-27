from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi import BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from socketio import AsyncServer, ASGIApp
from dotenv import load_dotenv
import sys
import traceback
import json
import random
import traceback
from dotenv import load_dotenv


# In-memory game store
TABLE_STORE = {}

sys.path.append("../")
from vanillapoker import poker, pokerutils

# Load environment variables from .env file
load_dotenv()


def generate_card_properties():
    """
    Use PRNG to deterministically generate random properties for the NFTs
    """
    import random

    random.seed(0)

    # Map from nft tokenId to properties
    nft_map = {}

    for i in range(1000):
        # Copying naming convention from solidity contract
        cardNumber = random.randint(0, 51)
        rarity = random.randint(1, 100)
        nft_map[i] = {"cardNumber": cardNumber, "rarity": rarity}

    return nft_map


# Storing NFT metadata properties locally for now - in future pull from chain
nft_map = generate_card_properties()


sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()

# Add CORS middleware to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Wrap the Socket.IO server with ASGI middleware
socket_app = ASGIApp(sio, other_asgi_app=app)


# Have to initialize the lookup tables before the API will work
def load_lookup_tables():
    with open("lookup_table_flushes.json", "r") as f:
        lookup_table_flush_5c = json.loads(f.read())

    with open("lookup_table_basic_7c.json", "r") as f:
        lookup_table_basic_7c = json.loads(f.read())

    return lookup_table_flush_5c, lookup_table_basic_7c


lookup_table_flush_5c, lookup_table_basic_7c = load_lookup_tables()
poker.PokerTable.set_lookup_tables(lookup_table_basic_7c, lookup_table_flush_5c)


# Define Socket.IO event handlers
@sio.event
async def connect(sid, environ):
    print("Client connected:", sid)


@sio.event
async def disconnect(sid):
    print("Client disconnected:", sid)


async def ws_emit_actions(table_id, poker_table_obj):
    # while True:
    #     is_event, event = poker_table_obj.get_next_event(0)
    #     if is_event:
    #         await sio.emit(table_id, event)
    #     else:
    #         break
    while poker_table_obj.events_pop:
        event = poker_table_obj.events_pop.pop(0)
        print("EMITTING EVENT", event)
        await sio.emit(table_id, event)


class ItemJoinTable(BaseModel):
    tableId: str
    address: str
    depositAmount: int
    seatI: int


class ItemLeaveTable(BaseModel):
    tableId: str
    address: str
    seatI: int


class ItemRebuy(BaseModel):
    tableId: str
    address: str
    rebuyAmount: str
    seatI: int


class ItemTakeAction(BaseModel):
    tableId: str
    address: str
    seatI: int
    actionType: int
    amount: int


class ItemCreateTable(BaseModel):
    smallBlind: int
    bigBlind: int
    minBuyin: int
    maxBuyin: int
    numSeats: int


@app.post("/joinTable")
async def join_table(item: ItemJoinTable):
    table_id = item.tableId
    player_id = item.address
    deposit_amount = item.depositAmount
    seat_i = item.seatI
    if table_id not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}
    poker_table_obj = TABLE_STORE[table_id]
    # Not using seat_i for now
    # poker_table_obj.join_table(seat_i, deposit_amount, player_id)
    poker_table_obj.join_table_next_seat_i(deposit_amount, player_id)
    await ws_emit_actions(table_id, poker_table_obj)
    return {"success": True}


@app.post("/leaveTable")
async def leave_table(item: ItemLeaveTable):
    table_id = item.tableId
    player_id = item.address
    seat_i = item.seatI
    if table_id not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}
    poker_table_obj = TABLE_STORE[table_id]
    # poker_table_obj.leave_table(seat_i, player_id)
    try:
        poker_table_obj.leave_table_no_seat_i(player_id)
    except:
        err = traceback.format_exc()
        return {"success": False, "error": err}

    await ws_emit_actions(table_id, poker_table_obj)
    return {"success": True}


@app.post("/rebuy")
async def rebuy(item: ItemRebuy):
    table_id = item.tableId
    player_id = item.address
    rebuy_amount = item.rebuyAmount
    seat_i = item.seatI
    if table_id not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}
    poker_table_obj = TABLE_STORE[table_id]
    # poker_table_obj.rebuy(seat_i, rebuy_amount, player_id)
    try:
        poker_table_obj.rebuy_no_seat_i(rebuy_amount, player_id)
    except:
        err = traceback.format_exc()
        return {"success": False, "error": err}

    await ws_emit_actions(table_id, poker_table_obj)
    return {"success": True}


@app.post("/takeAction")
async def take_action(item: ItemTakeAction):
    table_id = item.tableId
    player_id = item.address
    seat_i = item.seatI
    action_type = int(item.actionType)
    amount = int(item.amount)
    if table_id not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}
    poker_table_obj = TABLE_STORE[table_id]
    start_hand_stage = poker_table_obj.hand_stage

    try:
        poker_table_obj.take_action(action_type, player_id, amount)
    except:
        err = traceback.format_exc()
        return {"success": False, "error": err}

    await ws_emit_actions(table_id, poker_table_obj)

    # Only cache if we completed a hand!
    """
    end_hand_stage = poker_table_obj.hand_stage
    if end_hand_stage < start_hand_stage:
        print("UPDATING FOR TABLEID", table_id)
        try:
            update_table(table_id, poker_table_obj.serialize())
        except:
            err = traceback.format_exc()
            print("Intitial instantiation failed!", err)
            return False, {}
    """
    return {"success": True}


def gen_new_table_id():
    table_id = None
    while not table_id or table_id in TABLE_STORE:
        table_id = 10000 + int(random.random() * 990000)
    return str(table_id)


@app.post("/createNewTable")
async def create_new_table(item: ItemCreateTable):
    # Need validation here too?
    small_blind = item.smallBlind
    big_blind = item.bigBlind
    min_buyin = item.minBuyin
    max_buyin = item.maxBuyin
    num_seats = item.numSeats

    try:
        # Validate params...
        assert num_seats in [2, 6, 9]
        assert big_blind == small_blind * 2
        # Min_buyin
        assert 10 * big_blind <= min_buyin <= 400 * big_blind
        assert 10 * big_blind <= max_buyin <= 1000 * big_blind
        assert min_buyin <= max_buyin
        poker_table_obj = poker.PokerTable(
            small_blind, big_blind, min_buyin, max_buyin, num_seats
        )
        table_id = gen_new_table_id()
        TABLE_STORE[table_id] = poker_table_obj
    except:
        err = traceback.format_exc()
        return {"tableId": None, "success": False, "error": err}

    # And cache it!
    # store_table(table_id, poker_table_obj.serialize())

    # Does this make sense?  Returning null response for all others
    return {"success": True, "tableId": table_id}


@app.get("/getTables")
async def get_tables():
    # Example element...
    # {
    #     "tableId": 456,
    #     "numSeats": 6,
    #     "smallBlind": 1,
    #     "bigBlind": 2,
    #     "minBuyin": 20,
    #     "maxBuyin": 400,
    #     "numPlayers": 2,
    # },
    tables = []
    for table_id, table_obj in TABLE_STORE.items():
        num_players = len([seat for seat in table_obj.seats if seat is not None])
        table_info = {
            "tableId": table_id,
            "numSeats": table_obj.num_seats,
            "smallBlind": table_obj.small_blind,
            "bigBlind": table_obj.big_blind,
            "minBuyin": table_obj.min_buyin,
            "maxBuyin": table_obj.max_buyin,
            "numPlayers": num_players,
        }
        tables.append(table_info)
        print(table_id, table_obj)

    return {"tables": tables}


@app.get("/getTable")
async def get_table(table_id: str):
    if table_id not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}

    poker_table_obj = TABLE_STORE[table_id]

    players = [pokerutils.build_player_data(seat) for seat in poker_table_obj.seats]
    table_info = {
        "tableId": table_id,
        "numSeats": poker_table_obj.num_seats,
        "smallBlind": poker_table_obj.small_blind,
        "bigBlind": poker_table_obj.big_blind,
        "minBuyin": poker_table_obj.min_buyin,
        "maxBuyin": poker_table_obj.max_buyin,
        "players": players,
        "board": poker_table_obj.board,
        "pot": poker_table_obj.pot_total,
        "potInitial": poker_table_obj.pot_initial,
        "button": poker_table_obj.button,
        "whoseTurn": poker_table_obj.whose_turn,
        # name is string, value is int
        "handStage": poker_table_obj.hand_stage,
        "facingBet": poker_table_obj.facing_bet,
        "lastRaise": poker_table_obj.last_raise,
        "action": {
            "type": poker_table_obj.last_action_type,
            "amount": poker_table_obj.hand_stage,
        },
    }
    return {"table_info": table_info}


@app.get("/getHandHistory")
async def get_table(tableId: str, handId: int):
    if tableId not in TABLE_STORE:
        return {"success": False, "error": "Table not found!"}

    poker_table_obj = TABLE_STORE[tableId]
    if handId == -1:
        handIds = sorted(list(poker_table_obj.hand_histories.keys()))
        handId = handIds[-1]
    return {"hh": poker_table_obj.hand_histories[handId]}


# Hardcode this?  Figure out clean way to get it...
nft_owners = {"0xC52178a1b28AbF7734b259c27956acBFd67d4636": [0]}


@app.get("/getUserNFTs")
async def get_user_nfts(address: str):

    # Get a list of tokenIds of NFTs this user owns
    user_nfts = nft_owners.get(address, [])
    return {tokenId: nft_map[tokenId] for tokenId in user_nfts}


@app.get("/getNFTMetadata")
async def get_nft_metadata(tokenId: int):
    # {'cardNumber': 12, 'rarity': 73}
    return nft_map[tokenId]


# RUN:
# uvicorn fastapp:socket_app --host 127.0.0.1 --port 8000
