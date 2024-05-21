import eventlet

eventlet.monkey_patch()
import time
import threading
import random
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time

import sys

sys.path.append("../")
from vanillapoker import poker

app = Flask(__name__)
# TEMP - need to make this an environment variable
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)


# In-memory game store
TABLE_STORE = {}


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
    table_id = request.json["tableId"]
    player_id = request.json["address"]
    deposit_amount = request.json["depositAmount"]
    seat_i = request.json["seatI"]
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
    table_id = request.json["tableId"]
    player_id = request.json["address"]
    seat_i = request.json["seatI"]
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    poker_table_obj.leave_table(seat_i, player_id)
    ws_emit_actions(table_id, poker_table_obj)
    return jsonify({"success": True}), 200


@app.route("/rebuy", methods=["POST"])
def rebuy():
    table_id = request.json["tableId"]
    player_id = request.json["address"]
    rebuy_amount = request.json["rebuyAmount"]
    seat_i = request.json["seatI"]
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    poker_table_obj.rebuy(seat_i, rebuy_amount, player_id)
    ws_emit_actions(table_id, poker_table_obj)
    return jsonify({"success": True}), 200


@app.route("/takeAction", methods=["POST"])
def take_action():
    table_id = request.json["tableId"]
    player_id = request.json["address"]
    seat_i = request.json["seatI"]
    action_type = request.json["actionType"]
    amount = request.json["amount"]
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400
    poker_table_obj = TABLE_STORE[table_id]
    poker_table_obj.take_action(action_type, player_id, amount)
    ws_emit_actions(table_id, poker_table_obj)
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
    assert num_seats in [2, 6]
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
    table_id = request.args.get("table_id")
    if table_id not in TABLE_STORE:
        return jsonify({"success": False}), 400

    poker_table_obj = TABLE_STORE[table_id]

    fake_players = [
        {
            "address": "0x123",
            "stack": 88,
            "in_hand": True,
            "auto_post": False,
            "sitting_out": False,
            "bet_street": 17,
            "showdown_val": 8000,
            "holecards": [],
        },
        {
            "address": "0x456",
            "stack": 45,
            "in_hand": True,
            "auto_post": False,
            "sitting_out": False,
            "bet_street": 12,
            "showdown_val": 8000,
            "holecards": [],
        },
    ]

    table_info = {
        "tableId": table_id,
        "numSeats": poker_table_obj.num_seats,
        "smallBlind": poker_table_obj.small_blind,
        "bigBlind": poker_table_obj.big_blind,
        "minBuyin": poker_table_obj.min_buyin,
        "maxBuyin": poker_table_obj.max_buyin,
        "players": fake_players,  # poker_table_obj.seats,
        "board": poker_table_obj.board,
        "pot": poker_table_obj.pot,
        "button": poker_table_obj.button,
        "whoseTurn": poker_table_obj.whose_turn,
        # name is string, value is int
        "handStage": poker_table_obj.hand_stage.value,
    }
    return jsonify({"table_info": table_info}), 200


def ws_emit_actions(table_id, poker_table_obj):
    while poker_table_obj.events:
        event = poker_table_obj.events.pop(0)
        socketio.emit(table_id, event)


if __name__ == "__main__":
    # Start the background thread when the server starts
    thread = threading.Thread(target=ping_loop)
    thread.daemon = True
    thread.start()

    # socketio.run(app, debug=True)
    # To run on server, run this way
    socketio.run(app, host="0.0.0.0", debug=True)
