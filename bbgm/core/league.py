import random

from flask import session, g

from bbgm import app, db
from bbgm.core import play_menu, player, season
from bbgm.util import roster_auto_sort
import bbgm.util.const as c

def new(tid):
    # Add to main record
    g.dbex('INSERT INTO leagues (uid) VALUES (:uid)', uid=session['uid'])

    r = g.dbex('SELECT lid FROM leagues WHERE uid = :uid ORDER BY lid DESC LIMIT 1', uid=session['uid'])
    g.lid, = r.fetchone()

    # Create and connect to new database
    g.dbex('CREATE DATABASE bbgm_%s' % (g.lid,))
    g.dbex('GRANT ALL ON bbgm_%s.* TO %s@localhost IDENTIFIED BY \'%s\'' % (g.lid, app.config['DB_USERNAME'], app.config['DB_PASSWORD']))
    db.connect('bbgm_%d' % (g.lid,))

    # Copy team attributes table
    g.dbex('CREATE TABLE team_attributes SELECT * FROM bbgm.teams')

    # Create other new tables
    f = app.open_resource('data/league.sql')
    db.bulk_execute(f)

    # Generate new players
    profiles = ['Point', 'Wing', 'Big', '']
    gp = player.GeneratePlayer()
    pid = 1
    player_attributes = []
    player_ratings = []
    for t in range(-1, 30):
        good_neutral_bad = random.randrange(-1, 2)  # Determines if this will be a good team or not

        base_ratings = [30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 19, 19]
        pots = [70, 60, 50, 50, 55, 45, 65, 35, 50, 45, 55, 55, 40, 40]
        random.shuffle(pots)
        for p in range(14):
            i = random.randrange(len(profiles))
            profile = profiles[i]

            aging_years = random.randint(0, 16)

            draft_year = g.starting_season - 1 - aging_years

            gp.new(pid, t, 19, profile, base_ratings[p], pots[p], draft_year)
            gp.develop(aging_years)
            if p < 5:
                gp.bonus(good_neutral_bad * random.randint(0, 20))
            if t == -1:  # Free agents
                gp.bonus(-15)

            # Update contract based on development
            if t >= 0:
                randomize_expiration = True  # Players on teams already get randomized contracts
            else:
                randomize_expiration = False
            amount, expiration = gp.contract(randomize_expiration=randomize_expiration)
            gp.attribute['contract_amount'], gp.attribute['contract_exp'] = amount, expiration

            player_attributes.append(gp.get_attributes())
            player_ratings.append(gp.get_ratings())

            pid += 1
    g.dbexmany('INSERT INTO player_attributes (%s) VALUES (%s)' % (', '.join(player_attributes[0].keys()), ', '.join([':' + key for key in player_attributes[0].keys()])), player_attributes)
    g.dbexmany('INSERT INTO player_ratings (%s) VALUES (%s)' % (', '.join(player_ratings[0].keys()), ', '.join([':' + key for key in player_ratings[0].keys()])), player_ratings)

    # Set and get global game attributes
    g.dbex('UPDATE game_attributes SET tid = :tid', tid=tid)
    r = g.dbex('SELECT tid, season, phase, version FROM game_attributes LIMIT 1')
    g.user_tid, g.season, g.phase, g.version = r.fetchone()

    # Make schedule, start season
    season.new_phase(c.PHASE_REGULAR_SEASON)
    play_menu.set_status('Idle')

    # Auto sort player's roster (other teams will be done in season.new_phase(c.PHASE_REGULAR_SEASON))
    roster_auto_sort(g.user_tid)

    # Default trade settings
    if g.user_tid == 0:
        trade_tid = 1
    else:
        trade_tid = 0
    g.dbex('INSERT INTO trade (tid) VALUES (:tid)', tid=trade_tid)

    # Switch back to the default non-league database
    db.connect('bbgm')

    return g.lid

def delete(lid):
    g.dbex('DROP DATABASE bbgm_%s' % (lid,))
    g.dbex('DELETE FROM leagues WHERE lid = :lid', lid=lid)
