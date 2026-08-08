"""Ein echtes Orderbuch zum Anschauen - MLB gegen Counter-Strike."""
from lib.kalshi import KalshiClient
k = KalshiClient()

def zeig(serie, name):
    d = k._request("GET", "/markets", params={"series_ticker": serie,
                                              "status": "open", "limit": 60})
    ms = sorted(d.get("markets", []),
                key=lambda m: -float(m.get("volume_24h_fp") or 0))
    for m in ms[:1]:
        t = m["ticker"]
        ob = k.get_orderbook(t, depth=6).get("orderbook_fp", {})
        print(f"\n{'='*68}\n{name}: {m.get('title','')[:50]}\n{t}")
        print(f"{'='*68}")
        ja = [(float(p), float(n)) for p, n in (ob.get("yes_dollars") or [])]
        nein = [(float(p), float(n)) for p, n in (ob.get("no_dollars") or [])]
        # Nein-Gebote sind Ja-Briefkurse: Preis 1 - p
        briefe = sorted([(round(1 - p, 2), n) for p, n in nein])[:4]
        print("   VERKAEUFER (Briefkurs)")
        for p, n in reversed(briefe):
            print(f"      {p*100:5.0f} c   {n:12,.0f} Kontrakte")
        print("   ------------------------------ Spanne")
        print("   KAEUFER (Geldkurs)")
        for p, n in sorted(ja, reverse=True)[:4]:
            print(f"      {p*100:5.0f} c   {n:12,.0f} Kontrakte")
        best = max(ja)[0] if ja else 0.5
        print(f"\n   Unsere Order ueber 100 $ bei {best*100:.0f} c "
              f"= {100//best:.0f} Kontrakte")
        if ja:
            vor = max(ja, key=lambda x: x[0])[1]
            print(f"   Vor uns in der Schlange: {vor:,.0f} Kontrakte")
            print(f"   Unser Anteil an der Stufe: {100//best/(vor+100//best)*100:.2f} %")

zeig("KXMLBGAME", "MLB")
zeig("KXCS2GAME", "Counter-Strike 2")
