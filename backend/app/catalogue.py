"""The product catalogue, as the company publishes it.

Taken from the supplier's monthly order sheet for this cluster:
"Western Odisha_Order Sheet Nov'26-V1.xlsx", sheet "Order Sheet",
created 03-10-26 and stamped Version Oct2026-V1.

Straight from that sheet, per SKU: brand group, product name, pack size in
grams, packets per case, MRP, the company's basic rate per case, and the
purchase scheme %. The basic rate is 75.687% of the case's MRP value on
every one of the 105 lines, so it is one landing rate, not per-SKU pricing.

Two columns are NOT from the sheet and are defaults to confirm:

* `shelf` -- banded by product type (cakes 90 days, creams 180, the rest
  270). The sheet carries no dating.
* `velocity` -- relative off-take, banded by price point. It shapes the
  seeded demo history only and is never stored against a product.
"""

from decimal import Decimal

#: What the distributor pays the company per piece, before scheme, as a
#: fraction of MRP. Constant across the whole sheet.
LANDING_FRACTION_OF_MRP = Decimal("0.75687")

#: The supplier whose sheet this catalogue came from.
SUPPLIER = "Bhagwati"

#: sku, brand, name, pack_g, pieces/case, MRP, landing rate/piece (pre-GST,
#: before scheme), purchase scheme %, case weight kg, shelf-life days,
#: relative velocity
CATALOGUE = [
    ("KEK-RICFRU-032",    "Keki",                           "Keki Rich Fruit Cake Sliced",                               32,   60,  10, Decimal("7.5687"),  12, Decimal("2.4200"),   90,   5.0),
    ("KEK-RICPIN-032",    "Keki",                           "Keki Rich Pineapple Cake Sliced",                           32,   60,  10, Decimal("7.5687"),  12, Decimal("2.4200"),   90,   5.0),
    ("KEK-RICCHO-030",    "Keki",                           "Keki Rich Chocolate Cake Sliced",                           30,   60,  10, Decimal("7.5687"),  12, Decimal("2.3000"),   90,   5.0),
    ("KEK-RICORA-032",    "Keki",                           "Keki Rich Orange Cake Sliced",                              32,   60,  10, Decimal("7.5687"),  12, Decimal("2.4200"),   90,   5.0),
    ("KEK-RICBUT-030",    "Keki",                           "Keki Rich Butterscotch Cake Sliced",                        30,   60,  10, Decimal("7.5687"),  12, Decimal("2.3000"),   90,   5.0),
    ("KEK-RICMAR-030",    "Keki",                           "Keki Rich Marbel Cake Sliced",                              30,   60,  10, Decimal("7.5687"),  12, Decimal("2.3000"),   90,   5.0),
    ("KEK-TINTRE-016",    "Keki",                           "Keki Tiny Treat Vanilla - Vanilla Cream Filled Cup Cake",   16,   96,   5, Decimal("3.7843"),  12, Decimal("2.0360"),   90,   8.0),
    ("KEK-TINTRECHO-016", "Keki",                           "Keki Tiny Treat Choco - Vanilla Cream Filled Cup Cake",     16,   96,   5, Decimal("3.7843"),  12, Decimal("2.0360"),   90,   8.0),
    ("DM-DREMAR-395",     "Dream Marie",                    "Dream Marie",                                              395,   12,  50, Decimal("37.8434"),  10, Decimal("5.2400"),  270,   0.9),
    ("DM-DREMAR-245",     "Dream Marie",                    "Dream Marie",                                              245,   20,  30, Decimal("22.7060"),   8, Decimal("5.4000"),  270,   1.6),
    ("DM-DREMAR-137",     "Dream Marie",                    "Dream Marie",                                              137,   20,  20, Decimal("15.1373"),   8, Decimal("3.2400"),  270,   2.6),
    ("DM-DREMAR-070",     "Dream Marie",                    "Dream Marie",                                               70,   48,  10, Decimal("7.5687"),  14, Decimal("3.8600"),  270,   5.0),
    ("DM-DREMAR-035",     "Dream Marie",                    "Dream Marie",                                               35,  144,   5, Decimal("3.7843"),  14, Decimal("5.5400"),  270,   8.0),
    ("RT-RICTHI-230",     "Rich Thin",                      "Rich Thin",                                                230,   20,  30, Decimal("22.7060"),   8, Decimal("5.1000"),  270,   1.6),
    ("RT-RICTHI-035",     "Rich Thin",                      "Rich Thin",                                                 35,  144,   5, Decimal("3.7843"),  14, Decimal("5.5400"),  270,   8.0),
    ("CRA-HAMARA-132",    "Crackers",                       "Hamara Crackers",                                          132,   20,  20, Decimal("15.1373"),   8, Decimal("3.1400"),  270,   2.6),
    ("CRA-HAMARA-066",    "Crackers",                       "Hamara Crackers",                                           66,   30,  10, Decimal("7.5687"),  14, Decimal("2.4800"),  270,   5.0),
    ("CRA-HAMARA-033",    "Crackers",                       "Hamara Crackers",                                           33,  144,   5, Decimal("3.7843"),  14, Decimal("5.2520"),  270,   8.0),
    ("JC-HAMARA-058",     "Jeera Crackers",                 "Jeera Hamara Crackers",                                     58,   30,  10, Decimal("7.5687"),  14, Decimal("2.2400"),  270,   5.0),
    ("JC-HAMARA-029",     "Jeera Crackers",                 "Jeera Hamara Crackers",                                     29,  144,   5, Decimal("3.7843"),  14, Decimal("4.6760"),  270,   8.0),
    ("PVM-PROVIT-258",    "Pro Vita Marie",                 "Pro Vita Marie",                                           258,   20,  40, Decimal("30.2747"),   5, Decimal("5.6600"),  270,   1.2),
    ("SWE-SWEEP-126",     "Sweep",                          "Sweep",                                                    126,   20,  20, Decimal("15.1373"),   8, Decimal("3.0200"),  270,   2.6),
    ("SWE-SWEEP-057",     "Sweep",                          "Sweep",                                                     57,   30,  10, Decimal("7.5687"),  14, Decimal("2.2100"),  270,   5.0),
    ("SWE-SWEEP-036",     "Sweep",                          "Sweep",                                                     36,  144,   5, Decimal("3.7843"),  14, Decimal("5.6840"),  270,   8.0),
    ("SNA-SNAX-126",      "Snax",                           "Snax",                                                     126,   20,  20, Decimal("15.1373"),   8, Decimal("3.0200"),  270,   2.6),
    ("SNA-SNAX-064",      "Snax",                           "Snax",                                                      64,   30,  10, Decimal("7.5687"),  14, Decimal("2.4200"),  270,   5.0),
    ("SNA-SNAX-032",      "Snax",                           "Snax",                                                      32,  144,   5, Decimal("3.7843"),  14, Decimal("5.1080"),  270,   8.0),
    ("TL-TOPLIT-212",     "Top Lite",                       "Top Lite",                                                 212,   20,  30, Decimal("22.7060"),   8, Decimal("4.7400"),  270,   1.6),
    ("TL-TOPLIT-141",     "Top Lite",                       "Top Lite",                                                 141,   20,  20, Decimal("15.1373"),   8, Decimal("3.3200"),  270,   2.6),
    ("TL-TOPLIT-057",     "Top Lite",                       "Top Lite",                                                  57,   30,  10, Decimal("7.5687"),  14, Decimal("2.2100"),  270,   5.0),
    ("TL-TOPLIT-035",     "Top Lite",                       "Top Lite",                                                  35,  144,   5, Decimal("3.7843"),  14, Decimal("5.5400"),  270,   8.0),
    ("JT-LITE-141",       "Jeera Top",                      "Jeera Top Lite",                                           141,   20,  20, Decimal("15.1373"),   8, Decimal("3.3200"),  270,   2.6),
    ("JT-LITE-057",       "Jeera Top",                      "Jeera Top Lite",                                            57,   30,  10, Decimal("7.5687"),  14, Decimal("2.2100"),  270,   5.0),
    ("JT-TOPLIT-032",     "Jeera Top",                      "Jeera Toplite",                                             32,  144,   5, Decimal("3.7843"),  14, Decimal("5.1080"),  270,   8.0),
    ("BG-BUTGOL-291",     "Butter Gold",                    "Butter Gold Plus",                                         291,   15,  40, Decimal("30.2747"),   5, Decimal("4.8650"),  270,   1.2),
    ("BG-BUTGOL-212",     "Butter Gold",                    "Butter Gold Plus",                                         212,   20,  30, Decimal("22.7060"),   8, Decimal("4.7400"),  270,   1.6),
    ("BG-BUTGOL-135",     "Butter Gold",                    "Butter Gold Plus",                                         135,   20,  20, Decimal("15.1373"),   8, Decimal("3.2000"),  270,   2.6),
    ("BG-BUTGOL-062",     "Butter Gold",                    "Butter Gold Plus",                                          62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  270,   5.0),
    ("BG-BUTGOL-031",     "Butter Gold",                    "Butter Gold Plus",                                          31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  270,   8.0),
    ("BAC-NBG-124",       "BG Almond Cashew",               "NBG Almond Cashew",                                        124,   20,  20, Decimal("15.1373"),   8, Decimal("2.9800"),  270,   2.6),
    ("BAC-NBG-027",       "BG Almond Cashew",               "NBG Almond Cashew",                                         27,  144,   5, Decimal("3.7843"),  14, Decimal("4.3880"),  270,   8.0),
    ("7S-BUTGOL-077",     "7 Star",                         "7 Star Butter Gold",                                        77,   30,  10, Decimal("7.5687"),  14, Decimal("2.8100"),  270,   5.0),
    ("CG-CHOGOL-135",     "Chocco Gold",                    "Chocco Gold",                                              135,   20,  20, Decimal("15.1373"),   8, Decimal("3.2000"),  270,   2.6),
    ("CG-CHOGOL-031",     "Chocco Gold",                    "Chocco Gold",                                               31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  270,   8.0),
    ("TT-TTIM-300",       "T. Time",                        "T. Time",                                                  300,   15,  40, Decimal("30.2747"),  12, Decimal("5.0000"),  270,   1.2),
    ("TT-TTIM-144",       "T. Time",                        "T. Time",                                                  144,   20,  20, Decimal("15.1373"),   8, Decimal("3.3800"),  270,   2.6),
    ("TT-TTIM-072",       "T. Time",                        "T. Time",                                                   72,   40,  10, Decimal("7.5687"),  14, Decimal("3.3800"),  270,   5.0),
    ("AJ-BISK-150",       "Asli Jeera",                     "Jeera Bisk",                                               150,   20,  20, Decimal("15.1373"),   8, Decimal("3.5000"),  270,   2.6),
    ("AJ-BISK-038",       "Asli Jeera",                     "Jeera Bisk",                                                38,  144,   5, Decimal("3.7843"),  14, Decimal("5.9720"),  270,   8.0),
    ("SFCC-SUGFRE-270",   "Sugar Free Cream Cracker",       "Sugar Free Cream Cracker",                                 270,   15,  40, Decimal("30.2747"),   5, Decimal("4.5500"),  180,   1.2),
    ("SFCC-SUGFRE-132",   "Sugar Free Cream Cracker",       "Sugar Free Cream Cracker",                                 132,   20,  20, Decimal("15.1373"),   8, Decimal("3.1400"),  180,   2.6),
    ("SFCC-SUGFRE-066",   "Sugar Free Cream Cracker",       "Sugar Free Cream Cracker",                                  66,   40,  10, Decimal("7.5687"),  14, Decimal("3.1400"),  180,   5.0),
    ("SFCCJ-SUGFRE-270",  "Sugar Free Cream Cracker Jeera", "Sugar Free Cream Cracker Jeera",                           270,   15,  40, Decimal("30.2747"),   5, Decimal("4.5500"),  180,   1.2),
    ("SFCCJ-SUGFRE-132",  "Sugar Free Cream Cracker Jeera", "Sugar Free Cream Cracker Jeera",                           132,   20,  20, Decimal("15.1373"),   8, Decimal("3.1400"),  180,   2.6),
    ("SFCCJ-SUGFRE-066",  "Sugar Free Cream Cracker Jeera", "Sugar Free Cream Cracker Jeera",                            66,   40,  10, Decimal("7.5687"),  14, Decimal("3.1400"),  180,   5.0),
    ("CC-COCCRU-141",     "Coconut Crunch",                 "Coconut Crunch",                                           141,   20,  20, Decimal("15.1373"),   8, Decimal("3.3200"),  270,   2.6),
    ("CC-COCCRU-070",     "Coconut Crunch",                 "Coconut Crunch",                                            70,   40,  10, Decimal("7.5687"),  14, Decimal("3.3000"),  270,   5.0),
    ("CC-COCCRU-035",     "Coconut Crunch",                 "Coconut Crunch",                                            35,  144,   5, Decimal("3.7843"),  14, Decimal("5.5400"),  270,   8.0),
    ("SG-SUPG-168",       "Super G",                        "Super G",                                                  168,   20,  20, Decimal("15.1373"),   8, Decimal("3.8600"),  270,   2.6),
    ("SG-SUPG-084",       "Super G",                        "Super G",                                                   84,   60,  10, Decimal("7.5687"),  14, Decimal("5.5400"),  270,   5.0),
    ("SG-SUPG-042",       "Super G",                        "Super G",                                                   42,  144,   5, Decimal("3.7843"),  14, Decimal("6.5480"),  270,   8.0),
    ("SG-SUPG-023",       "Super G",                        "Super G",                                                   23,  144,   3, Decimal("2.2706"),   5, Decimal("3.8120"),  270,   9.0),
    ("BB-BIGBIS-135",     "Big Bisk",                       "Big Bisk",                                                 135,   20,  20, Decimal("15.1373"),   8, Decimal("3.2000"),  270,   2.6),
    ("BB-BIGBIS-034",     "Big Bisk",                       "Big Bisk",                                                  34,  144,   5, Decimal("3.7843"),  14, Decimal("5.3960"),  270,   8.0),
    ("PC-LEMONY-120",     "Puff Cream",                     "Cream Lemony Puff",                                        120,   20,  20, Decimal("15.1373"),   8, Decimal("2.9000"),  180,   2.6),
    ("PC-STRAWB-120",     "Puff Cream",                     "Cream Strawberry Puff",                                    120,   20,  20, Decimal("15.1373"),   8, Decimal("2.9000"),  180,   2.6),
    ("PC-CHOCOL-120",     "Puff Cream",                     "Cream Chocolaty Puff",                                     120,   20,  20, Decimal("15.1373"),   8, Decimal("2.9000"),  180,   2.6),
    ("PC-LEMONY-072",     "Puff Cream",                     "Cream Lemony Puff",                                         72,   60,  10, Decimal("7.5687"),  14, Decimal("4.8200"),  180,   5.0),
    ("PC-STRAWB-072",     "Puff Cream",                     "Cream Strawberry Puff",                                     72,   60,  10, Decimal("7.5687"),  14, Decimal("4.8200"),  180,   5.0),
    ("PC-CHOCOL-072",     "Puff Cream",                     "Cream Chocolaty Puff",                                      72,   60,  10, Decimal("7.5687"),  14, Decimal("4.8200"),  180,   5.0),
    ("PC-CHOCOL-028",     "Puff Cream",                     "Cream Chocolaty Puff",                                      28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("PC-CHOVAN-028",     "Puff Cream",                     "Cream Choco Vanilla Puff",                                  28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("PC-CHOORA-028",     "Puff Cream",                     "Cream Choco Orange Puff",                                   28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("PC-PINEAP-028",     "Puff Cream",                     "Cream Pineapple Puff",                                      28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("PC-LEMONY-028",     "Puff Cream",                     "Cream Lemony Puff",                                         28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("PC-STRAWB-028",     "Puff Cream",                     "Cream Strawberry Puff",                                     28,  144,   5, Decimal("3.7843"),  14, Decimal("4.5320"),  180,   8.0),
    ("CRE-BITCHO-031",    "Cream",                          "Cream Bites Choco Vanilla",                                 31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITECHOC-031",  "Cream",                          "Cream Bites Chocolate",                                     31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITCOC-031",    "Cream",                          "Cream Bites Coconut",                                       31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITELA-031",    "Cream",                          "Cream Bites Elaichi",                                       31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITELACOC-031", "Cream",                          "Cream Bites Elaichi Coconut",                               31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITLIT-031",    "Cream",                          "Cream Bites Litchi",                                        31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITMAN-031",    "Cream",                          "Cream Bites Mango",                                         31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITMIL-031",    "Cream",                          "Cream Bites Milk",                                          31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITCHA-031",    "Cream",                          "Cream Bites Chatpata Pink Guawa",                           31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITWAT-031",    "Cream",                          "Cream Bites Watermelon",                                    31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITBUT-029",    "Cream",                          "Cream Bites Butterscotch",                                  29,  144,   5, Decimal("3.7843"),  14, Decimal("4.6760"),  180,   8.0),
    ("CRE-BITCOC-029",    "Cream",                          "Cream Bites Coconut Chocolate",                             29,  144,   5, Decimal("3.7843"),  14, Decimal("4.6760"),  180,   8.0),
    ("CRE-BITORA-031",    "Cream",                          "Cream Bites Orange",                                        31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITSTR-031",    "Cream",                          "Cream Bites Strawberry",                                    31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  180,   8.0),
    ("CRE-BITCHO-062",    "Cream",                          "Cream Bites Chocolate",                                     62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  180,   5.0),
    ("CRE-BITORA-062",    "Cream",                          "Cream Bites Orange",                                        62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  180,   5.0),
    ("CRE-BITELA-062",    "Cream",                          "Cream Bites Elaichi",                                       62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  180,   5.0),
    ("CRE-BITMIL-062",    "Cream",                          "Cream Bites Milk",                                          62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  180,   5.0),
    ("CRE-BITSTR-062",    "Cream",                          "Cream Bites Strawberry",                                    62,   60,  10, Decimal("7.5687"),  14, Decimal("4.2200"),  180,   5.0),
    ("CRE-BITCHO-125",    "Cream",                          "Cream Bites Chocolate",                                    125,   20,  20, Decimal("15.1373"),   5, Decimal("3.0000"),  180,   2.6),
    ("CRE-BITORA-125",    "Cream",                          "Cream Bites Orange",                                       125,   20,  20, Decimal("15.1373"),   5, Decimal("3.0000"),  180,   2.6),
    ("CRE-BITELA-125",    "Cream",                          "Cream Bites Elaichi",                                      125,   20,  20, Decimal("15.1373"),   5, Decimal("3.0000"),  180,   2.6),
    ("CRE-BITSTR-125",    "Cream",                          "Cream Bites Strawberry",                                   125,   20,  20, Decimal("15.1373"),   5, Decimal("3.0000"),  180,   2.6),
    ("MB-MILBIT-036",     "Milki Bite",                     "Milki Bite",                                                36,  144,   5, Decimal("3.7843"),  14, Decimal("5.6840"),  180,   8.0),
    ("MB-MILBIT-072",     "Milki Bite",                     "Milki Bite",                                                72,   60,  10, Decimal("7.5687"),  14, Decimal("4.8200"),  180,   5.0),
    ("MB-MILBIT-150",     "Milki Bite",                     "Milki Bite",                                               150,   20,  20, Decimal("15.1373"),   5, Decimal("3.5000"),  180,   2.6),
    ("BNW-BLAN-031",      "Black N White",                  "Black N White",                                             31,  144,   5, Decimal("3.7843"),  14, Decimal("4.9640"),  270,   8.0),
    ("ROL-ROLGOL-150",    "Rolgol",                         "Rolgol",                                                   150,   20,  20, Decimal("15.1373"),   5, Decimal("3.5000"),  180,   2.6),
    ("ROL-ROLGOL-075",    "Rolgol",                         "Rolgol",                                                    75,   40,  10, Decimal("7.5687"),  14, Decimal("3.5000"),  180,   5.0),
]
