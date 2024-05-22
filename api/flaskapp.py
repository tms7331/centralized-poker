import eventlet

eventlet.monkey_patch()

import os
import time
import threading
import random
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import mysql.connector
import threading
import time

import sys

sys.path.append("../")
from vanillapoker import poker, pokerutils

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

# Database configuration
db_config = {
    "user": os.environ["SQL_USER"],
    "password": os.environ["SQL_PASS"],
    "host": os.environ["SQL_HOST"],
    "database": os.environ["SQL_DB"],
}

# In-memory game store
TABLE_STORE = {}


# Initialize database connection
def get_db_connection():
    return mysql.connector.connect(**db_config)


# Create a table (if it doesn't exist)
def init_db():
    print("Initializing db...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS poker_table_cache (
            table_id VARCHAR(10) NOT NULL,
            table_data TEXT NOT NULL,
            PRIMARY KEY (table_id)
        );
    """
    )
    conn.commit()
    cursor.close()
    conn.close()


def store_table(table_id, table_serialized):
    """
    Store a serialized poker table in our database
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO poker_table_cache (table_id, table_data) VALUES (%s, %s)",
        (table_id, table_serialized),
    )
    conn.commit()
    cursor.close()
    conn.close()


def retrieve_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    data = cursor.execute("SELECT * FROM poker_table_cache;")
    conn.commit()
    cursor.close()
    conn.close()
    return data


@socketio.on("connect")
def handle_connect():
    print("Client connected")


@socketio.on("disconnect")
def handle_disconnect():
    print("Client disconnected")


def ping_loop():
    count = 0
    while True:
        time.sleep(5)
        print("SENDING!!")
        count += 1
        # https://flask-socketio.readthedocs.io/en/latest/api.html#flask_socketio.SocketIO.emit
        socketio.emit("server_data", {"data": f"Server generated event {count}"})


@app.route("/joinTable", methods=["POST"])
def join_table():
    table_id = str(request.json["tableId"])
    player_id = request.json["address"]
    deposit_amount = int(request.json["depositAmount"])
    seat_i = int(request.json["seatI"])
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    # Not using seat_i for now
    # poker_table_obj.join_table(seat_i, deposit_amount, player_id)
    poker_table_obj.join_table_next_seat_i(deposit_amount, player_id)
    ws_emit_actions(table_id, poker_table_obj)
    return jsonify({"success": True}), 200


@app.route("/leaveTable", methods=["POST"])
def leave_table():
    table_id = str(request.json["tableId"])
    player_id = request.json["address"]
    seat_i = int(request.json["seatI"])
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    poker_table_obj.leave_table(seat_i, player_id)
    ws_emit_actions(table_id, poker_table_obj)
    return jsonify({"success": True}), 200


@app.route("/rebuy", methods=["POST"])
def rebuy():
    table_id = str(request.json["tableId"])
    player_id = request.json["address"]
    rebuy_amount = int(request.json["rebuyAmount"])
    seat_i = int(request.json["seatI"])
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    poker_table_obj.rebuy(seat_i, rebuy_amount, player_id)
    ws_emit_actions(table_id, poker_table_obj)
    return jsonify({"success": True}), 200


@app.route("/takeAction", methods=["POST"])
def take_action():
    table_id = str(request.json["tableId"])
    player_id = request.json["address"]
    seat_i = int(request.json["seatI"])
    action_type = int(request.json["actionType"])
    amount = int(request.json["amount"])
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    start_hand_stage = poker_table_obj.hand_stage
    poker_table_obj.take_action(action_type, player_id, amount)
    ws_emit_actions(table_id, poker_table_obj)

    # Only cache if we completed a hand!
    end_hand_stage = poker_table_obj.hand_stage
    if end_hand_stage < start_hand_stage:
        store_table(table_id, poker_table_obj.serialize())

    return jsonify({"success": True}), 200


def gen_new_table_id():
    table_id = None
    while not table_id or table_id in TABLE_STORE:
        table_id = 10000 + int(random.random() * 990000)
    return str(table_id)


@app.route("/createNewTable", methods=["POST"])
def create_new_table():
    # Need validation here too?
    small_blind = request.json["smallBlind"]
    big_blind = request.json["bigBlind"]
    min_buyin = request.json["minBuyin"]
    max_buyin = request.json["maxBuyin"]
    num_seats = request.json["numSeats"]

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

    # And cache it!
    store_table(table_id, poker_table_obj.serialize())

    # Does this make sense?  Returning null response for all others
    return jsonify({"tableId": table_id}), 200


@app.route("/getTables", methods=["GET"])
def get_tables():
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

    return jsonify({"tables": tables}), 200


@app.route("/getTable", methods=["GET"])
def get_table():
    table_id = str(request.args.get("table_id"))
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400

    poker_table_obj = TABLE_STORE[table_id]

    players = [pokerutils.build_player_data(seat) for seat in poker_table_obj.seats]

    print("SENDING BOARD!!!!")
    print(table_id)
    print(poker_table_obj.board)
    print("-----------------")

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
    return jsonify({"table_info": table_info}), 200


def ws_emit_actions(table_id, poker_table_obj):
    while poker_table_obj.events:
        event = poker_table_obj.events.pop(0)
        print("EMITTING EVENT", event)
        socketio.emit(table_id, event)


if __name__ == "__main__":
    init_db()
    # cached_tables = retrieve_tables()
    # for table in cached_tables:
    #     TABLE_STORE[table["table_id"]] = poker.PokerTable.deserialize(
    #         table["table_data"]
    #     )

    # Start the background thread when the server starts
    thread = threading.Thread(target=ping_loop)
    thread.daemon = True
    thread.start()

    # socketio.run(app, debug=True)
    # To run on server, run this way
    socketio.run(app, host="0.0.0.0", debug=True)
