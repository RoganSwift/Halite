# Python 3.6
# rules: https://web.archive.org/web/20181019011459/http://www.halite.io/learn-programming-challenge/game-overview

""" Stage 0: Imports - Permitted X minutes here
    Access to only code.    
"""

import sys
import json
import logging

# Import the Halite SDK, which will let you interact with the game.
import hlt
from hlt import constants, commands # This library contains constant values.
from hlt.positionals import Direction, Position # This library contains direction metadata to better interface with the game.

#sys.argv[0] is "MyBot.py", which we don't need to save.
if len(sys.argv) >= 2:
    logging_level = int(sys.argv[1])
else:
    logging_level = 0

def sc_log(level, message):
    '''Shortcut Log: if logging_level >= level: logging.info(message)'''
    if logging_level >= level:
        logging.info(message)

def spiral_walk(starting_x, starting_y):
    '''Spiral walk iterator: yield a position in the square spiral starting at x,y, walking x+1 and turning towards y-1'''
    sc_log(3, f"Walking a spiral from {starting_x},{starting_y}.")
    x,y = starting_x, starting_y
    yield Position(x,y)
    i = 1
    while True:
        for _ in range(i):
            x+=1
        yield Position(x,y)
        for _ in range(i):
            y-=1
            yield Position(x,y)
        i+=1
        for _ in range(i):
            x-=1
            yield Position(x,y)
        for _ in range(i):
            y+=1
            yield Position(x,y)
        i+=1

def dist_betw_positions(start, end):
    '''return (start.x-end.x)**2+(start.y-end.y)**2'''
    return (start.x-end.x)**2+(start.y-end.y)**2

def read_moved_ships(command_queue):
    return [ship_id for _, ship_id, _ in command_queue]

reverted_commands = {commands.NORTH: Direction.North,
                     commands.SOUTH: Direction.South,
                     commands.EAST:  Direction.East,
                     commands.WEST:  Direction.West,
                     commands.STAY_STILL: Direction.Still}

def read_committed_positions(ships, command_queue):
    return [ships[ship_id].position + reverted_commands[command] for _, ship_id, command in command_queue]

class FlinkBot():
    '''A bot (game state + behaviors) for the Halite competition. Initialization begins hlt.Game(). FlinkBot.ready() begins game.ready().'''
    def __init__(self):
        """ Stage 1: Pre-game scanning - Permitted X minutes here.
        Once game = hlt.Game() is run, you have access to the game map for computationally-intensive start-up pre-processing.
        """
        self.game = hlt.Game()
        self.game_map = self.game.game_map
        self.me = self.game.me
        self.ships = self.me.get_ships()

        if logging_level >= 1:
            map_array = [
                        [self.game_map[Position(x,y)].halite_amount for x in range(self.game_map.width)] for y in range(self.game_map.height)
                        ]
            sc_log(1, f"##FL-Map:{str(json.dumps(map_array))}")

        p = self.determine_personality_parameters(self.game_map)

        # Apply loaded personality parameters
        self.q = (p[0]*200, # 0 to 200 - Amount of halite in cell where ships consider it depleted.
            (0.5+p[1]*0.25)*constants.MAX_HALITE, # 50% to 75% of MAX_HALITE - amount of cargo above which ships believe they're returning cargo.
            1 + round(p[2]*29) # 1 to 30 - max number of bots
        )

    def determine_personality_parameters(self, game_map):
        # TODO: game_map is not currently used. The intention is to train a machine learning algorithm to determine these parameters from the game map.

        #sys.argv[0] is "MyBot.py", which we don't need to save.
        #sys.argv[1] is the logging level, which is captured elsewhere.

        # TODO: pickle_level as arg[2] removed. See if you can shift stuff up.

        # This is the list of personality parameters to be determined through machine learning.
        p = [0.5,
            0.5,
            0.5
        ] #TODO: Consider adding p[3] = cap on last round to make ships
        #TODO: Add halite depleted on turn 400; linear interpolation between two

        i = 0
        for arg in sys.argv[3:]:
            sc_log(1, f"Arg: {str(arg)}")
            p[i] = float(arg)
            i += 1
        
        return p

    def ready(self):
        """ Stage 2: Game Turns - Permitted 2 seconds per turn.
        Once game.ready("MyPythonBot") is run, you have access to positions of units and the ability to send commands.
        """
        self.game.ready("MyPythonBot")
        sc_log(1, "Successfully created bot! My Player ID is {}.".format(self.game.my_id))

    def update(self):
        self.game.update_frame() # pull updated data
        self.me = self.game.me
        self.ships = self.me.get_ships()

    def submit(self, command_queue):
        self.game.end_turn(command_queue)

    def one_game_step(self):
        """Determine and return the command_queue actions to take this turn."""
        sc_log(1, f"##FL-Round:{self.game.turn_number}:{self.game.me.halite_amount}")

        #TODO: Consider enemy positions when choosing to move
        #      If you can't grab a list of their positions, spiral_walk until you find the closest.
        for ship in self.ships:
            if ship.id not in read_moved_ships(command_queue):
                command_queue = self.move_ship_recursive(command_queue, ship, [])

        if self.me.halite_amount >= constants.SHIP_COST and self.me.shipyard.position not in read_committed_positions(self.ships, command_queue) and len(self.ships) <= self.q[2]:
            sc_log(2, "Generating new ship.")
            command_queue.append(self.me.shipyard.spawn())

        sc_log(1, f"Command queue: {str(command_queue)}")
        return command_queue

    def move_ship_recursive(self, command_queue, ship, ignore_ships):
        '''Determine ship movement, recursively deferring to a ship in its path and ignoring ships that are confirmed to move elsewhere.'''
        sc_log(1, f"Move_ship_recursion start: Ship {ship.id}")

        moved = False
        loopcounter = 0 # Infinite loops terrify me, so loopcounter has a max of 10, which should never occur. (Actual max 5)
        while not moved and loopcounter < 10:
            # Check for the ship's desired move, considering that it can't go to any committed positions
            move_direction, move_position = self.desired_move(ship, command_queue)
            sc_log(1, "Move_ship_recursion: Ship {ship.id} considering direction {move_direction} position {move_position}")
            # Collisions are only possible with ships meeting the following criteria:
            # (1) has not moved yet and (2) is currently on the target space
            #  - Ships after this ship won't target this target because it will be in the command queue once this ship commits
            #  - and this ship couldn't have targeted this space if another ship committed to staying still in it.
            # (3) is not higher in the recursive chain than this ship
            #  - you know any ship higher up the chain wants to move from its spot
            # To resolve this, check every ship for these three criteria
            no_ships_on_target = True
            for other_ship in self.ships:
                if ship.id != other_ship.id and other_ship.position == move_position and other_ship.id not in ignore_ships and other_ship.id not in read_moved_ships(command_queue):
                    sc_log(1, f"Move_ship_recursion: Ship {ship.id} blocked by {other_ship}. Letting it go first.")
                    # If one is found, let it move first, ignoring this ship (criteria (3) above)
                    command_queue = self.move_ship_recursive(command_queue, other_ship, [iship for iship in ignore_ships].append(ship.id))
                    # If that ship (or its down-chain friends) decided to commit this spot,
                    #   we need to restart the while loop and desired_move elsewhere.
                    if move_position in read_committed_positions(self.ships, command_queue):
                        no_ships_on_target = False
                        break

            # If, after looking at all other ships, none meet the criteria and want to stay, we can commit the move.
            if no_ships_on_target:
                if move_direction == "stay":
                    sc_log(1, f"Move_ship_recursion: Ship {ship.id} decided to stay at {ship.position}")
                    command_queue.append(ship.stay_still())
                else:
                    sc_log(1, f"Move_ship_recursion: Ship {ship.id} decided to move {move_direction} to {move_position}")
                    command_queue.append(ship.move(move_direction)) 
                moved = True
            
            loopcounter += 1
        
        # As above, if the while loop goes way beyond where it should, fail gracefully and log.
        if not moved:
            sc_log(1, f"FLWarning:Ship {ship.id} could not find a target in 10 checks")
            command_queue.append(ship.stay_still())

        return command_queue

    def desired_move(self, ship, command_queue):
        committed_positions = read_committed_positions(self.ships, command_queue)
        on_shipyard = (self.me.shipyard.position == ship.position)
        sc_log(3, f"Invalid Positions: {str(committed_positions)}")
        sc_log(2, "- Checking desired move for ship {}.".format(ship.id))
        position = ship.position
        target = self.determine_target(ship)

        if ship.halite_amount < self.game_map[ship.position].halite_amount*0.1 or position == target:
            return ("stay", position)

        sc_log(2, f"- - Desired move for ship {ship.id} is {str(target)}.")
        move_order = "stay"
        destination = position
        if on_shipyard:
            best_distance = 1000 # insist that ships move off the shipyard unless impossible
        else:
            best_distance = dist_betw_positions(position, target)

        options = [Direction.North, Direction.South, Direction.East, Direction.West]

        for option in options:
            diagonal_distance = dist_betw_positions(position + option, target)
            if diagonal_distance < best_distance and position + option not in committed_positions:
                move_order = option
                destination = position + option
                best_distance = diagonal_distance

        sc_log(2, f"- - Next step for ship {ship.id} is {str(move_order)} to {str(destination)}")        
        return (move_order, destination)

    def determine_target(self, ship):
        # If ship is full or (ship is on a drained square and carrying lots of halite)
        if ship.halite_amount == constants.MAX_HALITE or (ship.halite_amount > self.q[1] and self.game_map[ship.position].halite_amount < self.q[0]):
            sc_log(3, f"- - Target for ship {ship.id} is shipyard.")
            return self.me.shipyard.position
        else:
            cells_searched = 0
            for search_position in spiral_walk(ship.position.x, ship.position.y):
                sc_log(3, f"- - - Checking search position {str(search_position)} with {self.game_map[search_position].halite_amount} halite.")
                if self.game_map[search_position].halite_amount >= self.q[0]:
                    sc_log(3, f"- - - Target for ship {ship.id} is {str(search_position)}")
                    return search_position

                # If there is insufficient halite on the map (very high threshold for depleted), stop.
                cells_searched += 1
                if cells_searched > 4*max(constants.WIDTH, constants.HEIGHT)**2: # this is worst-case of sitting in a corner
                    sc_log(1, f"??? Search found insufficient halite on map - ordering ship not to move.")
                    return ship.position    

if __name__ == "__main__":
    flink_bot = FlinkBot() # Initialization runs hlt.Game() and starts X minute timer to do pre-processing
    flink_bot.ready() # Readying starts 2-second turn timer phase

    while True:
        # Grab updated game map details
        flink_bot.update()
        # Determine set of commands
        command_queue = flink_bot.one_game_step()
        # Submit commands
        flink_bot.submit(command_queue)
