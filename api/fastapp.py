import os
import sys
import traceback
import json
import random
import traceback
from web3 import Web3, AsyncWeb3
from eth_account import Account
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
import aiomysql
from contextlib import asynccontextmanager
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from socketio import AsyncServer, ASGIApp
from dotenv import load_dotenv


# In-memory game store
TABLE_STORE = {}

sys.path.append("../")
from vanillapoker import poker, pokerutils

# Load environment variables from .env file
load_dotenv()

infura_key = os.environ["INFURA_KEY"]
infura_url = f"https://base-sepolia.infura.io/v3/{infura_key}"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # await database.database.connect()
    pass
    yield
    pass
    # await database.database.disconnect()


app = FastAPI(lifespan=lifespan)

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


class CreateNftItem(BaseModel):
    tokenId: int
    address: str


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
    # try:
    poker_table_obj.leave_table_no_seat_i(player_id)
    # except:
    #     err = traceback.format_exc()
    #     return {"success": False, "error": err}

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
    # try:
    poker_table_obj.rebuy_no_seat_i(rebuy_amount, player_id)
    # except:
    #     err = traceback.format_exc()
    #     return {"success": False, "error": err}

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

    # try:
    poker_table_obj.take_action(action_type, player_id, amount)
    # except:
    #     err = traceback.format_exc()
    #     return {"success": False, "error": err}

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

    # try:
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
    # except:
    #     err = traceback.format_exc()
    #     return {"tableId": None, "success": False, "error": err}

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


def get_nft_holders():
    w3 = Web3(Web3.HTTPProvider(infura_url))
    nft_contract_address = "0xc87716e22EFc71D35717166A83eC0Dc751DbC421"

    nft_contract_abi = """
        [{
        "inputs": [
        {
            "internalType": "uint256",
            "name": "tokenId",
            "type": "uint256"
        }
        ],
        "name": "ownerOf",
        "outputs": [
        {
            "internalType": "address",
            "name": "",
            "type": "address"
        }
        ],
        "stateMutability": "view",
        "type": "function"
        }]
    """

    # Create a contract instance
    nft_contract = w3.eth.contract(address=nft_contract_address, abi=nft_contract_abi)
    holders = {}
    # total_supply = nft_contract.functions.totalSupply().call()
    # for token_id in range(total_supply):
    token_id = 1
    while True:
        try:
            owner = nft_contract.functions.ownerOf(token_id).call()
            if owner in holders:
                holders[owner].append(token_id)
            else:
                holders[owner] = [token_id]
            token_id += 1
        except:
            print("CRASEHD ON", token_id)
            break

    return holders


# Hardcode this?  Figure out clean way to get it...
# nft_owners = {"0xC52178a1b28AbF7734b259c27956acBFd67d4636": [0]}
# TODO - reenable this...
# print("SKIPPING NFT_OWNERS...")
# nft_owners = {}
nft_owners = get_nft_holders()


@app.get("/getUserNFTs")
async def get_user_nfts(address: str):
    # Get a list of tokenIds of NFTs this user owns
    user_nfts = nft_owners.get(address, [])
    return {tokenId: nft_map[tokenId] for tokenId in user_nfts}


@app.get("/getNFTMetadata")
async def get_nft_metadata(tokenId: int):
    # {'cardNumber': 12, 'rarity': 73}
    return nft_map[tokenId]


@app.post("/createNewNFT")
async def create_new_nft(item: CreateNftItem):
    """
    This will be called by the front end immediatly before
    the transaction is sent to the blockchain.  We should
    return the expected NFT number here.
    """
    # So ugly but we need to iterate?
    # next_token_id = 0
    # for owner in nft_owners:
    #     for token_id in nft_owners[owner]:
    #         next_token_id = max(next_token_id, token_id + 1)
    token_id = item.tokenId

    owner = item.address
    if owner in nft_owners:
        nft_owners[owner].append(token_id)
    else:
        nft_owners[owner] = [token_id]

    # {'cardNumber': 12, 'rarity': 73}
    # "tokenId": next_token_id,
    return nft_map[token_id]


async def get_db_connection():
    connection = await aiomysql.connect(
        host="localhost",
        port=3306,
        user="flask_user_0123",  # Replace with your MySQL username
        password="w2Cqb7uNSv!$QXITma8UMGj",  # Replace with your MySQL password
        db="users",
    )
    return connection


@app.get("/users")
async def read_users():
    connection = await get_db_connection()
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM user_balances")
        users = await cursor.fetchall()
    connection.close()
    print("GOT USERS", users)
    return users


class User(BaseModel):
    address: str
    onChainBal: int
    localBal: int
    inPlay: int


@app.post("/users")
async def create_user(user: User):
    connection = await get_db_connection()
    async with connection.cursor() as cursor:
        try:
            await cursor.execute(
                """
                INSERT INTO user_balances (address, onChainBal, localBal, inPlay) 
                VALUES (%s, %s, %s, %s)
            """,
                (
                    user.address,
                    user.onChainBal,
                    user.localBal,
                    user.inPlay,
                ),
            )
            await connection.commit()
        except Exception as e:
            await connection.rollback()
            raise HTTPException(status_code=400, detail="Error creating user") from e
    connection.close()
    return {"message": "User created successfully"}


class UserBalance(BaseModel):
    address: str
    onChainBal: int
    localBal: int
    inPlay: int


@app.put("/balances")
async def update_balance(balance: UserBalance):
    connection = await get_db_connection()
    async with connection.cursor() as cursor:
        try:
            await cursor.execute(
                """
                UPDATE user_balances 
                SET onChainBal = %s, localBal = %s, inPlay = %s 
                WHERE address = %s
            """,
                (balance.onChainBal, balance.localBal, balance.inPlay, balance.address),
            )
            await connection.commit()
        except Exception as e:
            await connection.rollback()
            raise HTTPException(status_code=400, detail="Error updating balance") from e
    connection.close()
    return {"message": "Balance updated successfully"}


@app.get("/balance_one")
async def read_balance_one(address: str):
    connection = await get_db_connection()
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            "SELECT * FROM user_balances WHERE address = %s", (address,)
        )
        balance = await cursor.fetchone()
        if balance is None:
            raise HTTPException(status_code=404, detail="User not found")
    connection.close()
    return balance


async def update():
    web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(infura_url))

    plypkr_address = "0x8eF85f1eE73444f711cC5EbfB78A61622860bE3B"
    token_vault_address = "0x3F19a833dac7286904304449d226bd63917b15c6"

    # plypkr = web3.eth.contract(address=plypkr_address, abi=plypkr_abi)
    token_vault = web3.eth.contract(address=token_vault_address, abi=token_vault_abi)

    private_key = os.environ["PRIVATE_KEY"]
    account = Account.from_key(private_key)
    # account = web3.eth.account.privateKeyToAccount(private_key)
    account_address = account.address

    # bal = await plypkr.functions.balanceOf(account_address).call()

    to = account_address
    amount = 1 * 10**18
    # Step 4: Call the withdraw function on the TokenVault contract
    withdraw_txn = await token_vault.functions.withdraw(to, amount).build_transaction(
        {
            "from": account_address,
            "nonce": web3.eth.get_transaction_count(account_address),
            # "gas": 2000000,
            # "gasPrice": web3.to_wei("50", "gwei"),
        }
    )
    signed_withdraw_txn = await web3.eth.account.sign_transaction(
        withdraw_txn, private_key=private_key
    )
    withdraw_txn_hash = await web3.eth.send_raw_transaction(
        signed_withdraw_txn.rawTransaction
    )
    print(f"Deposit transaction hash: {withdraw_txn_hash.hex()}")
    # await web3.eth.wait_for_transaction_receipt(withdraw_txn_hash)


@app.post("/deposited")
async def post_deposited():
    """
    After user deposits to contract, update their balance in the database
    """
    # So get the DIFF between what they have and what we've tracked

    # TODO -
    # update database with their new token balance...

    # Got it, just get it going

    # onChainBal
    # localBal
    # inPlay

    # So get the diff between our current

    return {"data": random.randint(0, 1_000_000)}


@app.get("/getTokenBalance")
async def get_token_balance(address: str):
    # Got it...
    # pull player information
    # token balance should be there...

    # TODO - pull from db
    # question - should we return token balance and inPlay balance separately?
    return {"data": random.randint(0, 1_000_000)}


@app.get("/getEarningRate")
async def get_earning_rate(address: str):
    # Get their NFTs - sum up the rarity values and divide by 100?  Or normalize?

    # TODO - add this in...

    # Just sum NFT rarities...
    return {"data": random.random()}


@app.get("/getRealTimeConversion")
async def get_real_time_conversion():
    # Divide token count by ETH count ...
    return {"data": random.random() * 1000}


# RUN:
# uvicorn fastapp:socket_app --host 127.0.0.1 --port 8000
