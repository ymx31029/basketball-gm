import math
import random
import sqlite3

from flask import g, jsonify, json

from bbgm import app
from bbgm.core import game_sim, season, play_menu
from bbgm.util import fast_random


class Game:
    def play(self, t1, t2, is_playoffs):
        # Run simulation and get stats
        print Team(t1).to_json()
        gs = game_sim.GameSim(Team(t1), Team(t2))
        self.team = gs.run()

        self.is_playoffs = is_playoffs
        self.id = random.randint(0, 100000000)
        self.season = g.season
        self.home = [True, False]
        self.team_id = [t1, t2]

        # What is the attendance of the game?
        g.db.execute('SELECT won+lost, 1.0*won/(won + lost) FROM %s_team_attributes WHERE season = %s AND (team_id = %s OR team_id = %s)', (g.league_id, self.season, self.team_id[0], self.team_id[1]))
        games_played, winp = g.db.fetchone()
        if games_played < 5:
            self.attendance = fast_random.gauss(22000 + games_played * 1000, 1000)
        else:
            self.attendance = fast_random.gauss(winp * 36000, 1000)
        if self.attendance > 25000:
            self.attendance = 25000
        elif self.attendance < 10000:
            self.attendance = 10000

        # Are the teams in the same conference/division?
        self.same_conference = False
        self.same_division = False
        conference_id = [-1, -1]
        division_id = [-1, -1]
        for t in range(2):
            g.db.execute('SELECT ld.conference_id, ta.division_id FROM %s_team_attributes as ta, %s_league_divisions as ld WHERE ta.team_id = %s AND ta.season = %s AND ta.division_id = ld.division_id', (g.league_id, g.league_id, self.team_id[t], self.season))
            row = g.db.fetchone()
            conference_id[t] = row[0]
            division_id[t] = row[1]
        if conference_id[0] == conference_id[1]:
            self.same_conference = True
        if division_id[0] == division_id[1]:
            self.same_division = True

    def write_stats(self):
        # Record who the starters are
        for t in range(2):
            g.db.execute('SELECT pa.player_id FROM %s_player_attributes as pa, %s_player_ratings as pr WHERE pa.player_id = pr.player_id AND pa.team_id = %s AND pr.roster_position <= 5', (g.league_id, g.league_id, self.team_id[t]))
            for row in g.db.fetchall():
                for p in range(self.team[t].num_players):
                    if self.team[t].player[p].id == row[0]:
                        self.record_stat(t, p, 'starter')

        # Player stats and team stats
        for t in range(2):
            self.write_team_stats(t)
            for p in range(self.team[t].num_players):
                self.write_player_stats(t, p)

    def write_player_stats(self, t, p):
        query = 'INSERT INTO %s_player_stats \
                 (player_id, team_id, game_id, season, is_playoffs, starter, minutes, field_goals_made, field_goals_attempted, three_pointers_made, three_pointers_attempted, free_throws_made, free_throws_attempted, offensive_rebounds, defensive_rebounds, assists, turnovers, steals, blocks, personal_fouls, points) \
                 VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
        g.db.execute(query, (g.league_id, self.team[t].player[p].id, self.team_id[t], self.id, self.season, self.is_playoffs, self.team[t].player[p].stat['starter'], int(round(self.team[t].player[p].stat['minutes'])), self.team[t].player[p].stat['field_goals_made'], self.team[t].player[p].stat['field_goals_attempted'], self.team[t].player[p].stat['three_pointers_made'], self.team[t].player[p].stat['three_pointers_attempted'], self.team[t].player[p].stat['free_throws_made'], self.team[t].player[p].stat['free_throws_attempted'], self.team[t].player[p].stat['offensive_rebounds'], self.team[t].player[p].stat['defensive_rebounds'], self.team[t].player[p].stat['assists'], self.team[t].player[p].stat['turnovers'], self.team[t].player[p].stat['steals'], self.team[t].player[p].stat['blocks'], self.team[t].player[p].stat['personal_fouls'], self.team[t].player[p].stat['points']))

    def write_team_stats(self, t):
        if t == 0:
            t2 = 1
        else:
            t2 = 0
        if self.team[t].stat['points'] > self.team[t2].stat['points']:
            won = True
            if self.is_playoffs and t == 0:
                g.db.execute('UPDATE %s_active_playoff_series SET won_home = won_home + 1 WHERE team_id_home = %s AND team_id_away = %s', (g.league_id, self.team_id[t], self.team_id[t2]))
            elif self.is_playoffs:
                g.db.execute('UPDATE %s_active_playoff_series SET won_away = won_away + 1 WHERE team_id_home = %s AND team_id_away = %s', (g.league_id, self.team_id[t2], self.team_id[t]))
        else:
            won = False

        # Only pay player salaries for regular season games.
        if not self.is_playoffs:
            g.db.execute('SELECT SUM(contract_amount) * 1000 / 82 FROM %s_released_players_salaries WHERE team_id = %s', (g.league_id, self.team_id[t]))
            cost_released, = g.db.fetchone()
            g.db.execute('SELECT SUM(contract_amount) * 1000 / 82 FROM %s_player_attributes WHERE team_id = %s', (g.league_id, self.team_id[t]))
            cost, = g.db.fetchone()
            if cost_released:
                cost += cost_released
        else:
            cost = 0
        g.db.execute('UPDATE %s_team_attributes SET cash = cash + %s - %s WHERE season = %s AND team_id = %s', (g.league_id, g.ticket_price * self.attendance, cost, self.season, self.team_id[t]))

        query = 'INSERT INTO %s_team_stats \
                 (team_id, opponent_team_id, game_id, season, is_playoffs, won, home, minutes, field_goals_made, field_goals_attempted, three_pointers_made, three_pointers_attempted, free_throws_made, free_throws_attempted, offensive_rebounds, defensive_rebounds, assists, turnovers, steals, blocks, personal_fouls, points, opponent_points, attendance, cost) \
                 VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
        g.db.execute(query, (g.league_id, self.team_id[t], self.team[t2].id, self.id, self.season, self.is_playoffs, won, self.home[t], int(round(self.team[t].stat['minutes'])), self.team[t].stat['field_goals_made'], self.team[t].stat['field_goals_attempted'], self.team[t].stat['three_pointers_made'], self.team[t].stat['three_pointers_attempted'], self.team[t].stat['free_throws_made'], self.team[t].stat['free_throws_attempted'], self.team[t].stat['offensive_rebounds'], self.team[t].stat['defensive_rebounds'], self.team[t].stat['assists'], self.team[t].stat['turnovers'], self.team[t].stat['steals'], self.team[t].stat['blocks'], self.team[t].stat['personal_fouls'], self.team[t].stat['points'], self.team[t2].stat['points'], self.attendance, cost))
        if won and not self.is_playoffs:
            g.db.execute('UPDATE %s_team_attributes SET won = won + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))
            if self.same_division:
                g.db.execute('UPDATE %s_team_attributes SET won_div = won_div + 1, won_conf = won_conf + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))
            elif self.same_conference:
                g.db.execute('UPDATE %s_team_attributes SET won_conf = won_conf + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))
        elif not self.is_playoffs:
            g.db.execute('UPDATE %s_team_attributes SET lost = lost + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))
            if self.same_division:
                g.db.execute('UPDATE %s_team_attributes SET lost_div = lost_div + 1, lost_conf = lost_conf + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))
            elif self.same_conference:
                g.db.execute('UPDATE %s_team_attributes SET lost_conf = lost_conf + 1 WHERE team_id = %s AND season = %s', (g.league_id, self.team_id[t], self.season))


class Team:
    def __init__(self, team_id):
        self.id = team_id
        self._initialize_stats()
        self.load_players()
        self.load_team_attributes()
        self.home = False

    def _initialize_stats(self):
        self.stat = dict(minutes=0, field_goals_made=0, field_goals_attempted=0,
                         three_pointers_made=0, three_pointers_attempted=0,
                         free_throws_made=0, free_throws_attempted=0,
                         offensive_rebounds=0, defensive_rebounds=0, assists=0,
                         turnovers=0, steals=0, blocks=0, personal_fouls=0,
                         points=0)

    def load_players(self):
        self.player = []
        self.player_ids = []
        p = 0
        g.db.execute('SELECT pa.player_id FROM %s_player_attributes as pa, %s_player_ratings as pr WHERE pa.player_id = pr.player_id AND pa.team_id = %s ORDER BY pr.roster_position ASC', (g.league_id, g.league_id, self.id))
        for row in g.db.fetchall():
            self.player.append(Player(row[0]))
            self.player_ids.append(row[0])
            p += 1
        self.num_players = p

    def load_team_attributes(self):
        """Load team attributes.

        This must be called after self.load_players to allow for generation of
        self.defense and self.pace.
        """
        g.db.execute('SELECT region, name FROM %s_team_attributes WHERE team_id = %s', (g.league_id, self.id))
        row = g.db.fetchone()
        self.region = row[0]
        self.name = row[1]

        # Number of players to factor into pace and defense rating calculation
        n_players = len(self.player)
        if n_players > 7:
            n_players = 7

        # Would be better if these were scaled by average minutes played and endurance
        self.pace = sum([self.player[i].composite_rating['pace'] for i in xrange(n_players)]) / 7
        self.defense = sum([self.player[i].composite_rating['defense'] for i in xrange(n_players)]) / 7 # 0 to 0.5
        self.defense /= 4 # This gives the percentage points subtracted from the other team's normal FG%

    def to_json(self):
        """Create JSON of minimal team attributes needed to simulate a game."""
        t = {'defense': self.defense, 'pace': self.pace, 'player_ids': self.player_ids, 'player': []}
        for p in self.player:
            t['player'].append({'overall_rating': p.overall_rating, 'stat': p.stat, 'composite_rating': p.composite_rating})
        return json.dumps(t)


class Player:
    def __init__(self, player_id):
        self.id = player_id
        self.load_ratings()
        self.overall_rating = self.rating['overall']
        self.make_composite_ratings()
        self._initialize_stats()

    # Load the raw rating values from the database
    def load_ratings(self):
        g.dbd.execute('SELECT overall, height, strength, speed, jumping, endurance, shooting_inside, shooting_layups, '
                'shooting_free_throws, shooting_two_pointers, shooting_three_pointers, blocks, steals, dribbling, '
                'passing, rebounding FROM %s_player_ratings WHERE player_id = %s', (g.league_id, self.id))
        self.rating = g.dbd.fetchone()
        g.dbd.execute('SELECT name, position FROM %s_player_attributes WHERE player_id = %s', (g.league_id, self.id))
        self.attribute = g.dbd.fetchone()

    def make_composite_ratings(self):
        self.composite_rating = {}
        self.composite_rating['pace'] = self._composite(90, 140, ['speed', 'jumping', 'shooting_layups',
                                                        'shooting_three_pointers', 'steals', 'dribbling',
                                                        'passing'], random=False)
        self.composite_rating['shot_ratio'] = self._composite(0, 0.5, ['shooting_inside', 'shooting_layups',
                                                              'shooting_two_pointers', 'shooting_three_pointers'])
        self.composite_rating['assist_ratio'] = self._composite(0, 0.5, ['dribbling', 'passing', 'speed'])
        self.composite_rating['turnover_ratio'] = self._composite(0, 0.5, ['dribbling', 'passing', 'speed'],
                                                                  inverse=True)
        self.composite_rating['field_goal_percentage'] = self._composite(0.38, 0.68, ['height', 'jumping',
                                                                         'shooting_inside', 'shooting_layups',
                                                                         'shooting_two_pointers',
                                                                         'shooting_three_pointers'])
        self.composite_rating['free_throw_percentage'] = self._composite(0.65, 0.9, ['shooting_free_throws'])
        self.composite_rating['three_pointer_percentage'] = self._composite(0, 0.45, ['shooting_three_pointers'])
        self.composite_rating['rebound_ratio'] = self._composite(0, 0.5, ['height', 'strength', 'jumping',
                                                                 'rebounding'])
        self.composite_rating['steal_ratio'] = self._composite(0, 0.5, ['speed', 'steals'])
        self.composite_rating['block_ratio'] = self._composite(0, 0.5, ['height', 'jumping', 'blocks'])
        self.composite_rating['foul_ratio'] = self._composite(0, 0.5, ['speed'], inverse=True)
        self.composite_rating['defense'] = self._composite(0, 0.5, ['strength', 'speed'])

    def _composite(self, minval, maxval, components, inverse=False, random=True):
        r = 0.0
        rmax = 0.0
        if inverse:
            sign = -1
            add = -100
        else:
            sign = 1
            add = 0
        for component in components:
            # Sigmoidal transformation
            y = (self.rating[component] - 70) / 10
            rcomp = y / math.sqrt(1 + pow(y, 2))
            rcomp = (rcomp + 1) * 50
#            rcomp = self.rating[component]

            r = r + sign * (add + rcomp)
            rmax = rmax + sign * (add + 100)
        # Scale from minval to maxval
        r = r / (100.0 * len(components))  # 0-1
#        r = r / (rmax * len(components))  # 0-1
        r = r * (maxval - minval) + minval  # Min-Max
        # Randomize: Mulitply by a random number from N(1,0.1)
        if random:
            r = fast_random.gauss(1, 0.1) * r
        return r

    def _initialize_stats(self):
        self.stat = dict(starter=0, minutes=0, field_goals_made=0, field_goals_attempted=0,
                         three_pointers_made=0, three_pointers_attempted=0,
                         free_throws_made=0, free_throws_attempted=0,
                         offensive_rebounds=0, defensive_rebounds=0, assists=0,
                         turnovers=0, steals=0, blocks=0, personal_fouls=0,
                         points=0, court_time=0, bench_time=0, energy=1)

def play(num_days):
    """Play num_days days worth of games.

    This function also handles a lot of the playoffs logic, for some reason.
    """

    games_in_progress(True)
    schedule = season.get_schedule()

    game = Game()
    for d in range(num_days):
        # Check if it's the playoffs and do some special stuff if it is
        if g.phase == 3:
            # Make today's  playoff schedule
            active_series = False
            num_active_teams = 0
            # Round: 1, 2, 3, or 4
            g.db.execute('SELECT MAX(series_round) FROM %s_active_playoff_series', (g.league_id,))
            current_round, = g.db.fetchone()

            g.db.execute('SELECT team_id_home, team_id_away FROM %s_active_playoff_series WHERE won_home < 4 AND won_away < 4 AND series_round = %s', (g.league_id, current_round))
            for team_id_home, team_id_away in g.db.fetchall():
                schedule.append([team_id_home, team_id_away])
                active_series = True
                num_active_teams += 2
            if not active_series:
                # The previous round is over

                # Who won?
                winners = {}
                for row in g.db.execute('SELECT series_id, team_id_home, team_id_away, seed_home, '
                                                 'seed_away, won_home, won_away FROM active_playoff_series WHERE '
                                                 'series_round = ? ORDER BY series_id ASC', (current_round,)):
                    series_id, team_id_home, team_id_away, seed_home, seed_away, won_home, won_away = row
                    if won_home == 4:
                        winners[series_id] = [team_id_home, seed_home]
                    else:
                        winners[series_id] = [team_id_away, seed_away]
                    # Record user's team as conference and league champion
                    if winners[series_id][0] == common.PLAYER_TEAM_ID and current_round == 3:
                        g.db.execute('UPDATE team_attributes SET won_conference = 1 WHERE season = ? AND '
                                              'team_id = ?', (g.season, common.PLAYER_TEAM_ID))
                    elif winners[series_id][0] == common.PLAYER_TEAM_ID and current_round == 4:
                        g.db.execute('UPDATE team_attributes SET won_championship = 1 WHERE season = ? AND '
                                              'team_id = ?', (g.season, common.PLAYER_TEAM_ID))

                # Are the whole playoffs over?
                if current_round == 4:
                    season.new_phase(4)
                    break

                # Add a new round to the database
                series_id = 1
                current_round += 1
                query = ('INSERT INTO active_playoff_series (series_id, series_round, team_id_home, team_id_away,'
                         'seed_home, seed_away, won_home, won_away) VALUES (?, ?, ?, ?, ?, ?, 0, 0)')
                for i in range(1, len(winners), 2):  # Go through winners by 2
                    if winners[i][1] < winners[i + 1][1]:  # Which team is the home team?
                        new_series = (series_id, current_round, winners[i][0], winners[i + 1][0], winners[i][1],
                                      winners[i + 1][1])
                    else:
                        new_series = (series_id, current_round, winners[i + 1][0], winners[i][0], winners[i + 1][1],
                                      winners[i][1])
                    g.db.execute(query, new_series)
                    series_id += 1
                continue
        else:
            # Decrease free agent demands
            g.db.execute('SELECT player_id, contract_amount, contract_expiration FROM %s_player_attributes WHERE team_id = -1 AND contract_amount > 500', (g.league_id,))
            for player_id, amount, expiration in g.db.fetchall():
                amount -= 50
                if amount < 500:
                    amount = 500
                if amount < 2000:
                    expiration = g.season + 1
                if amount < 1000:
                    expiration = g.season
                g.db.execute('UPDATE %s_player_attributes SET contract_amount = %s, contract_expiration = %s WHERE player_id = %s', (g.league_id, amount, expiration, player_id))

            # Free agents' resistance to previous signing attempts by player decays
            # Decay by 0.1 per game, for 82 games in the regular season
            g.db.execute('UPDATE %s_player_attributes SET free_agent_times_asked = free_agent_times_asked - 0.1 WHERE team_id = -1', (g.league_id,))
            g.db.execute('UPDATE %s_player_attributes SET free_agent_times_asked = 0 WHERE team_id = -1 AND free_agent_times_asked < 0', (g.league_id,))

            # Sign available free agents
#            self.auto_sign_free_agents()

        # If the user wants to stop the simulation, then stop the simulation
#        if d == 0:  # But not on the first day
#            self.stop_games = False
#        if self.stop_games:
#            self.stop_games = False
#            break

        if g.phase != 3:
            num_active_teams = g.num_teams

        play_menu.set_status('Playing day %d of %d...' % (d+1, num_days))
        for i in range(num_active_teams / 2):
            teams = schedule.pop()
            game.play(teams[0], teams[1], g.phase == 3)
            game.write_stats()
#        if self.phase == 3:
#            self.playoffs.updated = False
#            time.sleep(0.3)  # Or else it updates too fast to see what's going on
    play_menu.set_status('Idle')

#    season_over = False
    if g.phase == 3:
        pass
#        self.playoffs.updated = False
    else:
        # Check to see if the season is over
        g.db.execute('SELECT COUNT(*)/30 FROM %s_team_stats WHERE season = %s', (g.league_id, g.season))
        row = g.db.fetchone()
        days_played = row[0]
        if days_played == g.season_length:
#            season_over = True

            sew = season_end_window.SeasonEndWindow(self)
            sew.season_end_window.present()

            season.new_phase(3)  # Start playoffs

    season.set_schedule(schedule)
    games_in_progress(False)

def games_in_progress(status):
    g.db.execute('UPDATE %s_game_attributes SET games_in_progress = %s', (g.league_id, status))
