"""Nur die Siegermaerkte zaehlen - eine Partie, ein Eintrag.

Die vorige Liste zaehlte jede Partie mehrfach: MLB taucht als Sieger, Spread,
Total, Strikeouts, Home Runs usw. auf. Fuer die Frage "wieviele Spiele" zaehlt
nur der Siegermarkt.
"""
import datetime as dt, re, time
from collections import defaultdict
from lib.kalshi import KalshiClient
k = KalshiClient()

GRUPPEN = {
    "Tennis":       ["KXWTAMATCH","KXATPMATCH","KXATPCHALLENGERMATCH","KXITFMATCH",
                     "KXITFWMATCH","KXATPDOUBLES"],
    "Fussball":     ["KXCLUBFGAME","KXARGNACBGAME","KXARGPREMDIVGAME","KXCOPADOBRASILGAME",
                     "KXPERLIGA1GAME","KXNWSLGAME","KXECULPGAME","KXDIMAYORGAME",
                     "KXCHLLDPGAME","KXBOLPDIVGAME","KXLIGAMXGAME","KXHNLGAME",
                     "KXVENFUTVEGAME","KXAPFDDHGAME","KXELITESERIENGAME",
                     "KXEKSTRAKLASAGAME","KXDENSUPERLIGAGAME","KXCZEFLGAME","KXCANPLGAME"],
    "E-Sport":      ["KXCS2GAME","KXLOLGAME","KXDOTA2GAME","KXVALORANTGAME"],
    "Baseball":     ["KXMLBGAME","KXLMBGAME","KXKBOGAME"],
    "Basketball":   ["KXWNBAGAME","KXCEBLGAME","KXBIG3GAME","KXTBTGAME","KXBSNGAME"],
    "Cricket":      ["KXT20MATCH","KXTESTMATCH","KXHUNDREDMATCH"],
    "Lacrosse":     ["KXPLLGAME"],
}
NAMEN = {"KXMLBGAME":"MLB","KXLMBGAME":"Mexikanische Liga","KXKBOGAME":"KBO Korea",
         "KXWNBAGAME":"WNBA","KXLIGAMXGAME":"Liga MX","KXNWSLGAME":"NWSL",
         "KXDENSUPERLIGAGAME":"Daenemark Superliga","KXELITESERIENGAME":"Norwegen Eliteserien",
         "KXHNLGAME":"Kroatien HNL","KXEKSTRAKLASAGAME":"Polen Ekstraklasa",
         "KXCZEFLGAME":"Tschechien 1. Liga","KXCANPLGAME":"Kanada Premier League",
         "KXCLUBFGAME":"Freundschaftsspiele","KXARGNACBGAME":"Argentinien Nacional B",
         "KXARGPREMDIVGAME":"Argentinien Primera","KXCOPADOBRASILGAME":"Copa do Brasil",
         "KXPERLIGA1GAME":"Peru Liga 1","KXECULPGAME":"Ecuador Liga Pro",
         "KXDIMAYORGAME":"Kolumbien DIMAYOR","KXCHLLDPGAME":"Chile Primera",
         "KXBOLPDIVGAME":"Bolivien Primera","KXVENFUTVEGAME":"Venezuela FUTVE",
         "KXAPFDDHGAME":"Paraguay Division de Honor","KXCS2GAME":"Counter-Strike 2",
         "KXLOLGAME":"League of Legends","KXDOTA2GAME":"Dota 2","KXVALORANTGAME":"Valorant",
         "KXWTAMATCH":"WTA","KXATPMATCH":"ATP","KXATPCHALLENGERMATCH":"ATP Challenger",
         "KXITFMATCH":"ITF Herren","KXITFWMATCH":"ITF Damen","KXATPDOUBLES":"ATP Doppel",
         "KXT20MATCH":"T20","KXTESTMATCH":"Test Cricket","KXHUNDREDMATCH":"The Hundred",
         "KXCEBLGAME":"Kanada CEBL","KXBIG3GAME":"Big3","KXTBTGAME":"TBT",
         "KXBSNGAME":"Puerto Rico BSN","KXPLLGAME":"PLL Lacrosse"}

heute = dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).date()
erg = {}
for gruppe, serien in GRUPPEN.items():
    for ser in serien:
        try:
            d = k._request("GET", "/markets", params={"series_ticker": ser,
                                                      "status": "open", "limit": 500})
        except Exception:
            continue
        ev = defaultdict(list)
        for m in d.get("markets", []):
            ev[m.get("event_ticker") or m["ticker"]].append(m)
        spiele, tiefen, vol = 0, [], 0.0
        for e, g in ev.items():
            tr = re.search(r"-(\d{2}[A-Z]{3}\d{2})", e)
            if not tr: continue
            try:
                if dt.datetime.strptime(tr.group(1), "%y%b%d").date() != heute: continue
            except ValueError:
                continue
            spiele += 1
            vol += sum(float(x.get("volume_24h_fp") or 0) for x in g)
            tiefen += [float(x.get("yes_bid_size_fp") or 0) for x in g
                       if float(x.get("yes_bid_dollars") or 0) > 0]
        if spiele:
            tiefen.sort()
            erg.setdefault(gruppe, []).append(
                (spiele, NAMEN.get(ser, ser), vol,
                 tiefen[len(tiefen)//2] if tiefen else 0))
        time.sleep(0.03)

print(f"SIEGERMAERKTE AM {heute} (Ostkueste)\n")
gesamt = 0
for gruppe in sorted(erg, key=lambda g: -sum(x[0] for x in erg[g])):
    n = sum(x[0] for x in erg[gruppe])
    gesamt += n
    print(f"{gruppe.upper()}  —  {n} Partien")
    print(f"   {'Liga':30} {'Partien':>8} {'Umsatz 24h':>12} {'Tiefe Median':>13}")
    for spiele, name, vol, tiefe in sorted(erg[gruppe], reverse=True):
        print(f"   {name:30} {spiele:8} {vol:12,.0f} {tiefe:13,.0f}")
    print()
print(f"ZUSAMMEN {gesamt} Partien")
