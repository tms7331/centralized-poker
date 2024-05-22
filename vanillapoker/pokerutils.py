def build_player_data(seat):
    if seat is None:
        return None
    return {
        "address": seat["address"],
        "stack": seat["stack"],
        "inHand": seat["in_hand"],
        # "autoPost": seat["auto_post"],
        "sittingOut": seat["sitting_out"],
        "betStreet": seat["bet_street"],
        # "showdownVal": seat["showdown_val"],
        "holecards": seat["holecards"],
        "action": {
            "type": seat["last_action_type"],
            "amount": seat["last_amount"],
        },
    }
