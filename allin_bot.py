'''
All-In Bot — Goes all-in on every hand.
Simple, aggressive, and standalone for submission.
'''
import sys
import argparse
import socket
from collections import namedtuple

# ============================================================================
# ENGINE CORE (CONSOLIDATED)
# ============================================================================
GameInfo = namedtuple('GameInfo', ['bankroll', 'time_bank', 'round_num'])
HandResult = namedtuple('HandResult', ['payoffs', 'bids', 'parent_state'])

NUM_ROUNDS = 1000
STARTING_STACK = 5000
BIG_BLIND = 20
SMALL_BLIND = 10

ActionFold = namedtuple('ActionFold', [])
ActionCall = namedtuple('ActionCall', [])
ActionCheck = namedtuple('ActionCheck', [])
ActionRaise = namedtuple('ActionRaise', ['amount'])
ActionBid = namedtuple('ActionBid', ['amount'])

try:
    import eval7
except ImportError:
    pass

class GameState(namedtuple('_GameState', ['dealer', 'street', 'auction', 'bids', 'wagers', 'chips', 'hands', 'opp_hands', 'community_cards', 'parent_state'])):
    def get_street_name(self):
        if self.auction: return 'auction'
        return {0: 'pre-flop', 3: 'flop', 4: 'turn', 5: 'river'}[self.street]

    def calculate_result(self):
        score0 = eval7.evaluate(self.community_cards + self.hands[0])
        score1 = eval7.evaluate(self.community_cards + self.hands[1])
        if score0 > score1: delta = STARTING_STACK - self.chips[1]
        elif score0 < score1: delta = self.chips[0] - STARTING_STACK
        else: delta = (self.chips[0] - self.chips[1]) // 2
        return HandResult([delta, -delta], self.bids, self)

    def get_valid_actions(self):
        if self.auction: return {ActionBid}
        active_idx = self.dealer % 2
        cost = self.wagers[1-active_idx] - self.wagers[active_idx]
        if cost == 0:
            cannot_bet = (self.chips[0] == 0 or self.chips[1] == 0)
            return {ActionCheck} if cannot_bet else {ActionCheck, ActionRaise}
        cannot_raise = (cost == self.chips[active_idx] or self.chips[1-active_idx] == 0)
        return {ActionFold, ActionCall} if cannot_raise else {ActionFold, ActionCall, ActionRaise}

    def get_raise_limits(self):
        active_idx = self.dealer % 2
        cost = self.wagers[1-active_idx] - self.wagers[active_idx]
        max_bet = min(self.chips[active_idx], self.chips[1-active_idx] + cost)
        min_bet = min(max_bet, cost + max(cost, BIG_BLIND))
        return (self.wagers[active_idx] + min_bet, self.wagers[active_idx] + max_bet)

    def next_street(self):
        if self.street == 5: return self.calculate_result()
        if self.street == 0: return GameState(1, 3, True, self.bids, [0, 0], self.chips, self.hands, self.opp_hands, self.community_cards, self)
        return GameState(1, self.street+1, False, self.bids, [0, 0], self.chips, self.hands, self.opp_hands, self.community_cards, self)

    def apply_action(self, action):
        active = self.dealer % 2
        if isinstance(action, ActionFold):
            delta = self.chips[0] - STARTING_STACK if active == 0 else STARTING_STACK - self.chips[1]
            return HandResult([delta, -delta], self.bids, self)
        if isinstance(action, ActionCall):
            if self.dealer == 0:
                return GameState(1, 0, self.auction, self.bids, [BIG_BLIND]*2, [STARTING_STACK-BIG_BLIND]*2, self.hands, self.opp_hands, self.community_cards, self)
            next_wagers = list(self.wagers); next_chips = list(self.chips)
            amt = next_wagers[1-active] - next_wagers[active]
            next_chips[active] -= amt; next_wagers[active] += amt
            state = GameState(self.dealer+1, self.street, self.auction, self.bids, next_wagers, next_chips, self.hands, self.opp_hands, self.community_cards, self)
            return state.next_street()
        if isinstance(action, ActionCheck):
            if (self.street == 0 and self.dealer > 0) or self.dealer > 1: return self.next_street()
            return GameState(self.dealer+1, self.street, self.auction, self.bids, self.wagers, self.chips, self.hands, self.opp_hands, self.community_cards, self)
        if isinstance(action, ActionBid):
            next_bids = list(self.bids); next_bids[active] = action.amount
            if None not in next_bids:
                new_chips = list(self.chips); new_opp_hands = [list(h) for h in self.opp_hands]
                if next_bids[0] == next_bids[1]:
                    new_opp_hands[0].append(self.hands[1][0]); new_opp_hands[1].append(self.hands[0][0])
                    new_chips[0] -= next_bids[0]; new_chips[1] -= next_bids[1]
                else:
                    winner = 0 if next_bids[0] > next_bids[1] else 1; loser = 1 - winner
                    new_opp_hands[winner].append(self.hands[loser][0]); new_chips[winner] -= next_bids[loser]
                return GameState(1, self.street, False, next_bids, self.wagers, new_chips, self.hands, new_opp_hands, self.community_cards, self)
            return GameState(self.dealer+1, self.street, self.auction, next_bids, self.wagers, self.chips, self.hands, self.opp_hands, self.community_cards, self)
        next_wagers = list(self.wagers); next_chips = list(self.chips)
        added = action.amount - next_wagers[active]
        next_chips[active] -= added; next_wagers[active] += added
        return GameState(self.dealer+1, self.street, self.auction, self.bids, next_wagers, next_chips, self.hands, self.opp_hands, self.community_cards, self)


class PokerState:
    def __init__(self, state, active):
        self.is_terminal = isinstance(state, HandResult)
        current_state = state.parent_state if self.is_terminal else state
        self.street = current_state.get_street_name()
        self.my_hand = current_state.hands[active]
        self.board = current_state.community_cards
        self.opp_revealed_cards = current_state.opp_hands[active]
        self.my_chips = current_state.chips[active]
        self.opp_chips = current_state.chips[1-active]
        self.my_wager = current_state.wagers[active]
        self.opp_wager = current_state.wagers[1-active]
        self.pot = (STARTING_STACK - self.my_chips) + (STARTING_STACK - self.opp_chips)
        self.cost_to_call = self.opp_wager - self.my_wager
        self.is_bb = active == 1
        self.bids = list(current_state.bids)
        if self.is_terminal:
            self.legal_actions = set(); self.payoff = state.payoffs[active]; self.raise_bounds = (0, 0)
        else:
            self.legal_actions = current_state.get_valid_actions(); self.payoff = 0; self.raise_bounds = current_state.get_raise_limits()
    def can_act(self, action_cls): return action_cls in self.legal_actions


class BaseBot():
    def on_hand_start(self, game_info, current_state): pass
    def on_hand_end(self, game_info, current_state): pass
    def get_move(self, game_info, current_state): pass


# ============================================================================
# RUNNER
# ============================================================================
class Runner():
    def __init__(self, pokerbot, socketfile): self.pokerbot = pokerbot; self.socketfile = socketfile
    def receive(self):
        while True:
            packet = self.socketfile.readline().strip().split(' ')
            if not packet: break
            yield packet
    def send(self, action):
        if isinstance(action, ActionFold): code = 'F'
        elif isinstance(action, ActionCall): code = 'C'
        elif isinstance(action, ActionCheck): code = 'K'
        elif isinstance(action, ActionBid): code = 'A' + str(action.amount)
        else: code = 'R' + str(action.amount)
        self.socketfile.write(code + '\n'); self.socketfile.flush()
    def run(self):
        game_info = GameInfo(0, 0., 1); state = None; active = 0; round_flag = True
        for packet in self.receive():
            for clause in packet:
                if clause[0] == 'T': game_info = GameInfo(game_info.bankroll, float(clause[1:]), game_info.round_num)
                elif clause[0] == 'P': active = int(clause[1:])
                elif clause[0] == 'H':
                    hands = [[], []]; hands[active] = clause[1:].split(',')
                    wagers = [SMALL_BLIND, BIG_BLIND]; chips = [STARTING_STACK - SMALL_BLIND, STARTING_STACK - BIG_BLIND]
                    state = GameState(0, 0, False, [None, None], wagers, chips, hands, [[], []], [], None)
                    if round_flag: self.pokerbot.on_hand_start(game_info, PokerState(state, active)); round_flag = False
                elif clause[0] == 'F': state = state.apply_action(ActionFold())
                elif clause[0] == 'C': state = state.apply_action(ActionCall())
                elif clause[0] == 'K': state = state.apply_action(ActionCheck())
                elif clause[0] == 'R': state = state.apply_action(ActionRaise(int(clause[1:])))
                elif clause[0] == 'A': state = state.apply_action(ActionBid(int(clause[1:])))
                elif clause[0] == 'N':
                    chips, bids, opp_hands = clause[1:].split('_'); bids = [int(x) for x in bids.split(',')]
                    chips = [int(x) for x in chips.split(',')]; hands_active = [card for card in opp_hands.split(',') if card != '']
                    revised_hands = list(state.hands); revised_hands[active] = hands_active
                    state = GameState(state.dealer, state.street, state.auction, bids, state.wagers, chips, revised_hands, [[],[]], state.community_cards, state)
                elif clause[0] == 'B': state = GameState(state.dealer, state.street, state.auction, state.bids, state.wagers, state.chips, state.hands, state.opp_hands, clause[1:].split(','), state.parent_state)
                elif clause[0] == 'O':
                    state = state.parent_state; revised_hands = list(state.hands); revised_hands[1-active] = clause[1:].split(',')
                    revised_opp_hands = list(state.opp_hands); revised_opp_hands[active] = clause[1:].split(',')
                    state = GameState(state.dealer, state.street, state.auction, state.bids, state.wagers, state.chips, revised_hands, revised_opp_hands, state.community_cards, state.parent_state)
                    state = HandResult([0, 0], state.bids, state)
                elif clause[0] == 'D':
                    assert isinstance(state, HandResult); delta = int(clause[1:]); payoffs = [-delta, -delta]; payoffs[active] = delta
                    state = HandResult(payoffs, state.bids, state.parent_state); game_info = GameInfo(game_info.bankroll + delta, game_info.time_bank, game_info.round_num)
                    self.pokerbot.on_hand_end(game_info, PokerState(state, active)); game_info = GameInfo(game_info.bankroll, game_info.time_bank, game_info.round_num + 1); round_flag = True
                elif clause[0] == 'Q': return
            if round_flag: self.send(ActionCheck())
            else:
                action = self.pokerbot.get_move(game_info, PokerState(state, active))
                self.send(action)


# ============================================================================
# ALL-IN BOT
# ============================================================================
class Player(BaseBot):
    """Goes all-in every single hand. Maximum aggression."""

    def get_move(self, game_info, current_state):
        # Auction: bid 0 (don't waste chips on info)
        if current_state.street == 'auction':
            return ActionBid(0)

        # If we can raise, go all-in (max raise)
        if current_state.can_act(ActionRaise):
            _, max_raise = current_state.raise_bounds
            return ActionRaise(max_raise)

        # If we can call (someone else raised), always call
        if current_state.can_act(ActionCall):
            return ActionCall()

        # If we can only check, check
        if current_state.can_act(ActionCheck):
            return ActionCheck()

        # Should never reach here, but just in case
        return ActionFold()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('port', type=int)
    args = parser.parse_args()
    try:
        sock = socket.create_connection((args.host, args.port))
    except OSError:
        print(f'Could not connect to {args.host}:{args.port}')
        sys.exit(1)
    socketfile = sock.makefile('rw')
    runner = Runner(Player(), socketfile)
    runner.run()
    socketfile.close()
    sock.close()
