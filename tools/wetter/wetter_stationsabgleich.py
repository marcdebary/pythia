"""Wie weit liegt das Modellgitter je Stadt von der Abrechnungsstation?"""
import time
from lib import weather_reference as wr
print(f"{'Stadt':6} {'Station':8} {'Versatz':>9} {'Reststreuung':>13} {'Tage':>5}  Urteil")
print("-" * 62)
for stadt in sorted(wr.STATIONEN):
    a = wr.stationsabgleich(stadt, "max")
    u = ("ok" if a["ok"] and abs(a["versatz"]) < 3 and a["streuung"] < 2.5 else
         "grosser Versatz" if a["ok"] and abs(a["versatz"]) >= 3 else
         "unruhig" if a["ok"] else "KEIN ABGLEICH")
    print(f"{stadt:6} {wr.STATIONEN[stadt]['station']:8} {a['versatz']:+8.2f} F "
          f"{a['streuung']:12.2f} F {a['n']:5}  {u}")
    time.sleep(0.1)
