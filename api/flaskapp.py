import eventlet

eventlet.monkey_patch()
import time
import threading
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import time

app = Flask(__name__)
# TEMP - need to make this an environment variable
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)


# TEMP - hardcode handId to get fake data going
handId = 123


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
        socketio.emit(handId, {"data": f"Server generated event {count}"})


@app.route("/joinTable", methods=["POST"])
def join_table():
    player = request.json["player"]
    deposit_amount = request.json["depositAmount"]
    seat = request.json["seat"]
    socketio.emit(
        handId,
        {"tag": "rebuy", "player": player, "seat": seat, "action": deposit_amount},
    )
    return jsonify({"success": True}), 200


@app.route("/leaveTable", methods=["POST"])
def leave_table():
    player = request.json["player"]
    seat = request.json["seat"]
    socketio.emit(handId, {"tag": "leaveTable", "player": player, "seat": seat})
    return jsonify({"success": True}), 200


@app.route("/rebuy", methods=["POST"])
def rebuy():
    player = request.json["player"]
    deposit_amount = request.json["depositAmount"]
    seat = request.json["seat"]
    socketio.emit(
        handId,
        {"tag": "rebuy", "player": player, "seat": seat, "action": deposit_amount},
    )
    return jsonify({"success": True}), 200


@app.route("/takeAction", methods=["POST"])
def take_action():
    player = request.json["player"]
    seat = request.json["seat"]
    action = request.json["seat"]
    socketio.emit(
        handId, {"tag": "action", "player": player, "seat": seat, "action": action}
    )
    return jsonify({"success": True}), 200


if __name__ == "__main__":
    # Start the background thread when the server starts
    thread = threading.Thread(target=ping_loop)
    thread.daemon = True
    thread.start()

    socketio.run(app, debug=True)
    # To run on server, run this way
    # socketio.run(app, host="0.0.0.0", debug=True)
