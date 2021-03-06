import os
import psycopg2
import urlparse
import requests
import time
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def load_constants():
    cur = conn.cursor()
    cur.execute("SELECT session_id, steam_api_key FROM constants")
    data = cur.fetchone()
    cur.close()
    return data

def upsert_ranks(ranks):
    cur = conn.cursor()
    columns_str = ""
    values_str = ""
    for key, value in ranks.items():
        columns_str += "\"" + key + "\"" + ","
        values_str += "'" + str(value) + "'"  + ","
    columns_str += "\"last_update\""
    values_str += "now()"
    cur.execute("INSERT INTO player ({0}) VALUES ({1}) ON CONFLICT (id) DO UPDATE SET ({0}) = ({1})".format(columns_str, values_str))
    conn.commit()
    cur.close()

def get_players():
    cur = conn.cursor()
    cur.execute("SELECT platform, id FROM player")
    data = cur.fetchall()
    cur.close()
    return data

def get_headers():
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "SessionID" : SESSION_ID
    }

def get_rp_from_mmr(mmr):
    return int(mmr * 20 + 100)

def extract_rank(parsed_line):
    playlist = PLAYLIST_MAP[parsed_line['Playlist'][0]]
    rp = get_rp_from_mmr(float(parsed_line['MMR'][0]))
    rank = {}
    rank[playlist] = rp
    rank[playlist + "_games_played"] = int(parsed_line['MatchesPlayed'][0])
    rank[playlist + "_tier"] = int(parsed_line['Tier'][0])
    rank[playlist + "_division"] = int(parsed_line['Division'][0])
    return rank

def get_steam_name(id):
    response = requests.get("http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={0}&steamids={1}".format(STEAM_API_KEY, id))
    return response.json()['response']['players'][0]['personaname'].encode('utf-8')

def keep_alive():
    headers = get_headers()
    body = {
        "PlaylistID": 0,
        "NumLocalPlayers": 1
    }
    response = requests.post(API_ENDPOINT + UPDATE_ENDPOINT, headers=headers, data=body, verify=False)

def get_ranks(platform, id):
    headers = get_headers()

    body = {
        "Proc[]": "GetPlayerSkillSteam" if platform == 0 else "GetPlayerSkillPS4",
        "P0P[]": id
    }
    name = id if platform == 1 else get_steam_name(id) # fetch steam name
    response = requests.post(API_ENDPOINT + CALLPROC_ENDPOINT, headers=headers, data=body, verify=False)

    # Invalid session
    if (response.text.strip() == "SCRIPT ERROR SessionNotActive:"):
        return False

    lines = response.text.strip().split("\r\n")
    ranks = {"id": id, "platform": platform, "name": name}
    for line in lines[1:]:
        parsed_line = urlparse.parse_qs(line)
        rank_obj = extract_rank(parsed_line)
        ranks.update(rank_obj)
    return ranks


urlparse.uses_netloc.append("postgres")
with open("db_url.txt", "r") as f:
    DB_URL = f.read().replace('\n', '')
if not DB_URL:
    print("Put the database url in db_url.txt")
    quit()
url = urlparse.urlparse(DB_URL)

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)

VALID_SESSION = True

SESSION_ID, STEAM_API_KEY = load_constants()

API_ENDPOINT = "https://psyonix-rl.appspot.com/"
CALLPROC_ENDPOINT = "callproc105/"
UPDATE_ENDPOINT  = "Population/UpdatePlayerCurrentGame/"

PLAYLIST_MAP = {
        "10": "1v1",
        "11": "2v2",
        "12": "3v3s",
        "13": "3v3"
}

while(True):
    print("Starting full update...")
    players = get_players()
    for player in players:
        print("Pulling data for player: " + str(player[1]))
        ranks = get_ranks(int(player[0]), player[1])

        # session is invalid
        if not ranks:
            print("Our session was invalidated")
            VALID_SESSION = False
            break
            
        upsert_ranks(ranks)
        print("Player " + str(player[1]) + " updated")
    
    if VALID_SESSION:
        print("Sending keep alive request...")
        keep_alive()
        print("Finished update, waiting 15 minutes...")
        time.sleep(60 * 15) # sleep for 15 minutes

    while not VALID_SESSION:
        print("Trying to get a new session...")
        NEW_SESSION_ID, _ = load_constants()
        print(SESSION_ID, NEW_SESSION_ID)
        if NEW_SESSION_ID != SESSION_ID:
            print("Got a new session")
            SESSION_ID = NEW_SESSION_ID
            VALID_SESSION = True
            break
        print("Did not get a new session, trying again in 5 minutes")

        time.sleep(60 * 5) # sleep for 5 minutes
        


    