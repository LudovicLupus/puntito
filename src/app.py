import random
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "your-secret-key"  # Replace with a secure key in production

########################################
# Game Logic Classes and Helper Methods
########################################


class Player:
    def __init__(self, name):
        self.name = name
        self.total_score = 0  # Banked score
        self.previous_score = 0  # Score before last turn (for collision rollback)
        self.consecutive_busts = 0  # Two puntitos in a row
        self.entered = False  # Must score at least 300 in one turn to “enter”

    def __repr__(self):
        return f"<Player {self.name}: {self.total_score}>"


class Turn:
    def __init__(self, player):
        self.player = player
        self.dice_remaining = 5  # Start with 5 dice
        self.turn_total = 0  # Points accumulated during the turn
        self.last_roll = []  # The dice from the last roll
        self.last_roll_desc = ""  # Description of how the roll scored
        self.forced_reroll = False  # Whether the current turn is under forced re-roll


class Game:
    def __init__(self):
        self.players = []
        self.current_player_index = 0
        self.current_turn = None
        self.started = False
        self.winner = None

    def add_player(self, name):
        self.players.append(Player(name))

    def start_game(self):
        if self.players:
            self.started = True
            self.current_turn = Turn(self.players[self.current_player_index])

    def next_turn(self):
        # Save the current player's score as "previous" before moving on.
        self.current_turn.player.previous_score = self.current_turn.player.total_score
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_turn = Turn(self.players[self.current_player_index])

    def check_collisions(self):
        """
        If after banking, another player has the same total score,
        that other player’s score is rolled back to its previous value.
        """
        current = self.current_turn.player
        for p in self.players:
            if p is not current and p.total_score == current.total_score:
                flash(
                    f"Collision! {p.name} had the same score as {current.name} and is knocked back.",
                    "warning",
                )
                p.total_score = p.previous_score

    def check_winner(self):
        # First player to reach 5000 or more points wins.
        if self.current_turn.player.total_score >= 5000:
            self.winner = self.current_turn.player.name
            self.started = False


# Global game instance.
game = Game()


def roll_dice(n):
    """Roll n six‐sided dice and return the list of outcomes."""
    return [random.randint(1, 6) for _ in range(n)]


def is_escalera(dice):
    """
    Returns True if the 5 dice (in any order) form one of the allowed escalera sequences.
    Allowed sequences: [1,2,3,4,5], [2,3,4,5,6], or [3,4,5,6,1].
    """
    if len(dice) != 5:
        return False
    allowed_sets = [{1, 2, 3, 4, 5}, {2, 3, 4, 5, 6}, {1, 3, 4, 5, 6}]
    return set(dice) in allowed_sets


def score_roll(dice):
    """
    Given a list of dice values, compute the points earned, how many dice were used,
    and return a description.

    Scoring rules:
      - Escalera: If 5 dice form an allowed sequence, scores 500 points.
      - Three-of-a-kind: scores 100x the number (three 1's score 1000).
      - Each additional one scores 100 and each five scores 50.

    Returns a tuple: (score, dice_used, description)
    """
    # Check for escalera first:
    if len(dice) == 5 and is_escalera(dice):
        return 500, 5, "Escalera! (500 points)"

    score = 0
    dice_used = 0
    description_parts = []

    # Count occurrences of each die value.
    counts = {}
    for d in dice:
        counts[d] = counts.get(d, 0) + 1

    # Check for three-of-a-kind.
    for num in range(1, 7):
        if counts.get(num, 0) >= 3:
            if num == 1:
                score += 1000
                description_parts.append("Three 1's (1000)")
            else:
                score += num * 100
                description_parts.append(f"Three {num}'s ({num * 100})")
            dice_used += 3
            counts[num] -= 3

    # Count individual ones and fives.
    ones = counts.get(1, 0)
    if ones:
        score += ones * 100
        dice_used += ones
        description_parts.append(f"{ones} one(s) ({ones * 100})")
    fives = counts.get(5, 0)
    if fives:
        score += fives * 50
        dice_used += fives
        description_parts.append(f"{fives} five(s) ({fives * 50})")

    description = ", ".join(description_parts)
    return score, dice_used, description


########################################
# Flask Routes and Views
########################################


@app.route("/")
def index():
    """Display the current game state."""
    return render_template("index.html", game=game)


@app.route("/join", methods=["POST"])
def join():
    """Join the game by providing a name."""
    name = request.form.get("name")
    if name:
        game.add_player(name)
        flash(f"{name} has joined the game!", "info")
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
def start():
    """Start the game (requires at least one player)."""
    if not game.players:
        flash("Please add at least one player first!", "danger")
    else:
        game.start_game()
        flash("Game started!", "success")
    return redirect(url_for("index"))


@app.route("/roll", methods=["POST"])
def roll():
    """
    Handle a dice roll. The logic is as follows:
      - Roll the number of dice specified by turn.dice_remaining.
      - Score the roll.
      - If no dice scored (a bust), record a puntito (and if two puntitos occur in a row,
        revert to the previous score, then end the turn).
      - Otherwise, add the roll score to the turn total.
      - If the roll’s score is divisible by 50 but not equal to 100 (including escalera),
        force a re-roll with one fewer dice than were rolled this time.
      - If not forced, subtract the number of scoring dice from dice_remaining.
      - If no dice remain, the player “gets hot dice” and rolls all 5 again.
    """
    if not game.started:
        flash("The game has not started yet.", "warning")
        return redirect(url_for("index"))

    turn = game.current_turn
    dice_to_roll = turn.dice_remaining
    dice = roll_dice(dice_to_roll)
    turn.last_roll = dice

    roll_score, used, roll_desc = score_roll(dice)

    if used == 0:
        # Bust (puntito)
        turn.player.consecutive_busts += 1
        flash(
            f"{turn.player.name} rolled {dice} and got no scoring dice. (Puntito!)",
            "danger",
        )
        if turn.player.consecutive_busts >= 2:
            flash(
                f"{turn.player.name} got two puntitos in a row! Falling back to previous score.",
                "warning",
            )
            turn.player.total_score = turn.player.previous_score
            turn.player.consecutive_busts = 0
        game.next_turn()
        return redirect(url_for("index"))

    # Successful scoring roll: update the turn total.
    turn.turn_total += roll_score

    # Determine if forced re-roll applies:
    # Forced re-roll if the roll's score is divisible by 50 BUT not exactly 100.
    forced = roll_score % 50 == 0 and roll_score != 100
    if forced:
        new_dice_count = dice_to_roll - 1  # one fewer than the dice used this roll
        if new_dice_count <= 0:
            new_dice_count = (
                5  # If reduced to 0, "hot dice" rule: re-roll with all 5 dice.
            )
        turn.dice_remaining = new_dice_count
        turn.forced_reroll = True
        flash(
            f"{turn.player.name} rolled {dice} -> {roll_desc} for {roll_score} points. "
            f"Forced re-roll: you must roll with {new_dice_count} dice. Turn total is now {turn.turn_total}.",
            "info",
        )
    else:
        # Normal update: subtract the number of dice that scored.
        turn.dice_remaining -= used
        turn.forced_reroll = False
        if turn.dice_remaining == 0:
            turn.dice_remaining = 5
            flash(
                f"Hot dice! {turn.player.name} used all dice and gets a new set of 5.",
                "info",
            )
        flash(
            f"{turn.player.name} rolled {dice} -> {roll_desc} for {roll_score} points. "
            f"Turn total is now {turn.turn_total}. {turn.dice_remaining} dice remain.",
            "success",
        )
    return redirect(url_for("index"))


@app.route("/bank", methods=["POST"])
def bank():
    """
    Bank the current turn’s points into the player's total score.
    Banking is disallowed if a forced re-roll is in effect.
    Also, a player must score at least 300 in a turn to “enter” the game.
    After banking, collisions are checked and win conditions evaluated.
    """
    if not game.started:
        flash("The game has not started.", "warning")
        return redirect(url_for("index"))
    turn = game.current_turn
    player = turn.player

    # Disallow banking when a forced re-roll is required.
    if turn.forced_reroll:
        flash(
            "You must re-roll due to the forced re-roll rule before banking!", "danger"
        )
        return redirect(url_for("index"))

    # Enforce entry: if the player hasn't entered, they must score at least 300 in one turn.
    if not player.entered and turn.turn_total < 300:
        flash(
            f"{player.name} needs at least 300 points in one turn to enter! You only scored {turn.turn_total}.",
            "danger",
        )
        player.consecutive_busts += 1
        game.next_turn()
        return redirect(url_for("index"))

    player.previous_score = player.total_score
    player.total_score += turn.turn_total
    player.consecutive_busts = 0  # Reset bust count on a successful bank.
    if not player.entered:
        player.entered = True
        flash(f"{player.name} is now officially in the game!", "success")
    flash(
        f"{player.name} banks {turn.turn_total} points for a new total of {player.total_score}!",
        "info",
    )

    game.check_collisions()
    game.check_winner()
    if game.winner:
        flash(f"Game over! {game.winner} wins!", "success")
        game.started = False
        return redirect(url_for("index"))

    game.next_turn()
    return redirect(url_for("index"))


@app.route("/reset", methods=["POST"])
def reset():
    """Reset the game state."""
    global game
    game = Game()
    flash("Game reset.", "info")
    return redirect(url_for("index"))


########################################
# Run the Flask App
########################################

if __name__ == "__main__":
    app.run(debug=True)
