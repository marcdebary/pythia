"""Milwaukee bei den Angels: was kostet die Wette, was bringt sie, was sagt die Referenz."""
import math, sqlite3, datetime as dt
from lib.kalshi import KalshiClient
k = KalshiClient()

T = "KXMLBGAME-26AUG021515MILLAA-MIL"
m = k._request("GET", f"/markets/{T}").get("market", {})
print(f"{m.get('title')}  —  {m.get('yes_sub_title')}")
print(f"Status {m.get('status')}   Anpfiff/Oeffnung {m.get('open_time')}  "
      f"Schluss {m.get('close_time')}")
bid = float(m.get("yes_bid_dollars")); ask = float(m.get("yes_ask_dollars"))
print(f"Geldkurs {bid*100:.0f} c   Briefkurs {ask*100:.0f} c   "
      f"Tiefe Geld {float(m.get('yes_bid_size_fp') or 0):,.0f}  "
      f"Brief {float(m.get('yes_ask_size_fp') or 0):,.0f}")

EINSATZ = 100.0
print("\n" + "=" * 74)
print("VARIANTE A: SOFORT NEHMEN (Kauf zum Briefkurs)")
print("=" * 74)
n = int(EINSATZ // ask)
kosten = n * ask
geb = math.ceil(round(0.07 * n * ask * (1 - ask) * 100, 9)) / 100
print(f"   {n} Kontrakte a {ask*100:.0f} c        = {kosten:7.2f} $")
print(f"   Gebuehr (Nehmer, 7 %-Formel)   = {geb:7.2f} $")
print(f"   Gesamteinsatz                  = {kosten+geb:7.2f} $")
print(f"   Milwaukee gewinnt  -> {n} x 1 $ = {n:7.2f} $   Gewinn {n-kosten-geb:+7.2f} $")
print(f"   Milwaukee verliert -> 0 $         Verlust {-(kosten+geb):+7.2f} $")
print(f"   Einstiegspreis inkl. Gebuehr: {(kosten+geb)/n*100:.2f} c")

print("\n" + "=" * 74)
print("VARIANTE B: STELLEN (eigenes Gebot zum Geldkurs)")
print("=" * 74)
n2 = int(EINSATZ // bid)
kosten2 = n2 * bid
geb2 = math.ceil(0.0175 * n2 * bid * (1 - bid) * 100) / 100
print(f"   {n2} Kontrakte a {bid*100:.0f} c        = {kosten2:7.2f} $")
print(f"   Maker-Gebuehr (MLB zahlt)      = {geb2:7.2f} $")
print(f"   Gesamteinsatz                  = {kosten2+geb2:7.2f} $")
print(f"   Milwaukee gewinnt  -> {n2} x 1 $ = {n2:7.2f} $   Gewinn {n2-kosten2-geb2:+7.2f} $")
print(f"   Einstiegspreis inkl. Gebuehr: {(kosten2+geb2)/n2*100:.2f} c")
print(f"   ABER: {float(m.get('yes_bid_size_fp') or 0):,.0f} Kontrakte stehen vor dir.")

print("\n" + "=" * 74)
print("WAS SAGT DIE REFERENZ?")
print("=" * 74)
c = sqlite3.connect("/data/pythia.db"); c.row_factory = sqlite3.Row
r = c.execute("SELECT * FROM reference_observations WHERE market_ticker LIKE ?"
              " ORDER BY observed_at DESC LIMIT 1", ("%MILLAA%",)).fetchone()
if r:
    print(f"   Beobachtet {dt.datetime.fromtimestamp(r['observed_at'], dt.timezone.utc):%d.%m %H:%M} UTC")
    print(f"   {r['outcome']}  faire Wkt aus {r['n_books']} Buechern ({r['devig_method']}): "
          f"{float(r['fair_prob'])*100:.1f} %")
    print(f"   Kalshi damals: Geld {float(r['k_bid'] or 0)*100:.0f} c  "
          f"Brief {float(r['k_ask'] or 0)*100:.0f} c")
else:
    print("   Keine Beobachtung zu diesem Spiel im Buch.")
