"""Демонстрационный источник: детерминированные синтетические объявления BMW/Mercedes-Benz/Audi.

ВАЖНО: это не реальные данные. Время «публикации» новых демо-объявлений тоже синтетическое, поэтому
метрики задержки в демо-режиме не отражают реальную работу площадок."""
import hashlib
import math
import random
from datetime import timedelta

from ..schemas import RawListing
from ..timeutil import utcnow
from .base import FetchContext, FetchResult, SourceAdapter

# (бренд, модель, код поколения-как-в-названии, годы, базовая цена нового, [(название, объём, топливо, л.с.)],
#  КПП, привод, кузов)
ARCH = [
    ("BMW", "3 серии", "E90", (2005, 2012), 3_100_000,
     [("320i", 2.0, "бензин", 150), ("325i", 2.5, "бензин", 218), ("330i", 3.0, "бензин", 258), ("320d", 2.0, "дизель", 177)],
     ["автомат", "механика"], ["задний"], "седан"),
    ("BMW", "3 серии", "F30", (2012, 2018), 3_400_000,
     [("320i", 2.0, "бензин", 184), ("328i", 2.0, "бензин", 245), ("320d", 2.0, "дизель", 184)],
     ["автомат"], ["задний", "полный"], "седан"),
    ("BMW", "5 серии", "E60", (2003, 2010), 3_900_000,
     [("523i", 2.5, "бензин", 177), ("530i", 3.0, "бензин", 258), ("525d", 2.5, "дизель", 197)],
     ["автомат"], ["задний"], "седан"),
    ("BMW", "5 серии", "F10", (2010, 2016), 4_300_000,
     [("520i", 2.0, "бензин", 184), ("528i", 2.0, "бензин", 245), ("530d", 3.0, "дизель", 249)],
     ["автомат"], ["задний", "полный"], "седан"),
    ("BMW", "X5", "E70", (2006, 2013), 5_200_000,
     [("xDrive30d", 3.0, "дизель", 235), ("xDrive35i", 3.0, "бензин", 306)], ["автомат"], ["полный"], "внедорожник"),
    ("BMW", "X3", "F25", (2010, 2017), 3_900_000,
     [("xDrive20d", 2.0, "дизель", 184), ("xDrive28i", 2.0, "бензин", 245)], ["автомат"], ["полный"], "внедорожник"),
    ("Mercedes-Benz", "C-класс", "W204", (2007, 2014), 3_000_000,
     [("C 180", 1.6, "бензин", 156), ("C 200", 1.8, "бензин", 184), ("C 250", 1.8, "бензин", 204), ("C 220 CDI", 2.1, "дизель", 170)],
     ["автомат", "механика"], ["задний"], "седан"),
    ("Mercedes-Benz", "C-класс", "W205", (2014, 2020), 3_500_000,
     [("C 180", 1.6, "бензин", 156), ("C 200", 2.0, "бензин", 184), ("C 220 d", 2.1, "дизель", 170)],
     ["автомат"], ["задний"], "седан"),
    ("Mercedes-Benz", "E-класс", "W212", (2009, 2016), 4_000_000,
     [("E 200", 1.8, "бензин", 184), ("E 250", 2.0, "бензин", 211), ("E 300", 3.0, "бензин", 252), ("E 220 CDI", 2.1, "дизель", 170)],
     ["автомат"], ["задний", "полный"], "седан"),
    ("Mercedes-Benz", "E-класс", "W211", (2002, 2009), 3_800_000,
     [("E 200", 1.8, "бензин", 163), ("E 280", 3.0, "бензин", 231), ("E 320 CDI", 3.0, "дизель", 224)],
     ["автомат"], ["задний"], "седан"),
    ("Mercedes-Benz", "GLK", "X204", (2008, 2015), 3_600_000,
     [("GLK 250", 2.1, "дизель", 204), ("GLK 300", 3.0, "бензин", 231)], ["автомат"], ["полный"], "внедорожник"),
    ("Audi", "A4", "B8", (2007, 2014), 2_800_000,
     [("2.0 TFSI", 2.0, "бензин", 180), ("1.8 TFSI", 1.8, "бензин", 160), ("2.0 TDI", 2.0, "дизель", 143)],
     ["автомат", "механика", "вариатор"], ["передний", "полный"], "седан"),
    ("Audi", "A6", "C7", (2011, 2018), 3_900_000,
     [("2.0 TFSI", 2.0, "бензин", 180), ("3.0 TFSI", 3.0, "бензин", 300), ("3.0 TDI", 3.0, "дизель", 245)],
     ["автомат"], ["полный", "передний"], "седан"),
    ("Audi", "A6", "C6", (2004, 2011), 3_400_000,
     [("2.4", 2.4, "бензин", 177), ("3.2 FSI", 3.2, "бензин", 255), ("2.7 TDI", 2.7, "дизель", 190)],
     ["автомат"], ["полный", "передний"], "седан"),
    ("Audi", "Q5", "8R", (2008, 2016), 3_700_000,
     [("2.0 TFSI", 2.0, "бензин", 211), ("2.0 TDI", 2.0, "дизель", 177)], ["автомат"], ["полный"], "внедорожник"),
    ("Audi", "Q7", "4L", (2006, 2015), 5_000_000,
     [("3.0 TDI", 3.0, "дизель", 245), ("3.6", 3.6, "бензин", 280)], ["автомат"], ["полный"], "внедорожник"),
]
CITIES = [("Ростов-на-Дону", "Ростовская область", 5), ("Таганрог", "Ростовская область", 1),
          ("Краснодар", "Краснодарский край", 5), ("Сочи", "Краснодарский край", 1),
          ("Новороссийск", "Краснодарский край", 1), ("Ставрополь", "Ставропольский край", 1),
          ("Волгоград", "Волгоградская область", 1), ("Майкоп", "Республика Адыгея", 1),
          ("Воронеж", "Воронежская область", 1), ("Москва", "Москва", 2), ("Казань", "Республика Татарстан", 1)]
REGION_FACTOR = {"Москва": 1.08, "Республика Татарстан": 0.99}

GOOD = ["Один хозяин, обслужен, сервисная книжка.", "Не бит, не крашен, родной пробег.",
        "Состояние отличное, все ТО у дилера.", "Полная комплектация, кожа, камера, климат.",
        "Куплен в салоне, второй владелец."]
NEUTRAL = ["Машина в хорошем состоянии, торг при осмотре.", "Продаю личный автомобиль, документы в порядке.",
           "Эксплуатировался в городе, расходники менялись.", "Зимняя резина в подарок.", "Обмен не интересует."]
BAD = ["Была в ДТП, требует вложений.", "Срочная продажа, стучит подвеска, нужен ремонт.",
       "Крашен крыло и бампер, мелкие дефекты.", "Проблемы с коробкой, продаю на запчасти.",
       "Пробег скручен ранее, цена ниже рынка."]


class DemoSource(SourceAdapter):
    name = "demo"
    title = "Демо (синтетические данные)"
    is_demo = True
    status_note = "Синтетические данные для демонстрации; не реальный источник."

    def __init__(self, seed: int = 42, initial: int = 450, live: bool = True):
        self.seed, self.initial, self.live = seed, initial, live
        self._rng = random.Random(seed * 7919 + 13)
        self._live_items: list[RawListing] = []
        self._polls = 0

    def configured(self) -> bool:
        return True

    @staticmethod
    def _price(rng: random.Random, arch, year: int, km: int, region: str, seller: str) -> int:
        age = max(1, 2026 - year)
        base = arch[4] * max(0.12, 0.93 ** age)
        expected = age * 15_000
        base *= 1 - max(-0.2, min(0.25, 0.005 * (km - expected) / 10_000))
        base *= REGION_FACTOR.get(region, 1.0)
        if seller == "dealer":
            base *= 1.07
        base *= math.exp(rng.gauss(0, 0.07))
        roll = rng.random()
        if roll < 0.06:
            base *= rng.uniform(0.62, 0.88)   # сильно дешевле рынка
        elif roll < 0.08:
            base *= rng.uniform(1.25, 1.5)    # завышенная цена
        return int(round(base / 5000) * 5000)

    def _make(self, rng: random.Random, sid: str, posted_at, structured: bool) -> RawListing:
        # смещаем выбор к старым поколениям (бюджет 0.5–1 млн)
        weights = [3 if a[3][0] < 2012 else 1.4 for a in ARCH]
        arch = rng.choices(ARCH, weights=weights)[0]
        brand, model, gen, (y0, y1), _, engines, trans_opts, drives, body = arch
        year = rng.randint(y0, y1)
        eng = rng.choice(engines)
        trans = rng.choice(trans_opts)
        drive = rng.choice(drives)
        city, region, _w = rng.choices(CITIES, weights=[c[2] for c in CITIES])[0]
        seller = "private" if rng.random() < 0.7 else "dealer"
        age = max(1, 2026 - year)
        km = max(3_000, int(age * 15_000 * math.exp(rng.gauss(0, 0.35))))
        km = int(round(km, -3))
        price = self._price(rng, arch, year, km, region, seller)
        mood = rng.random()
        text = rng.choice(NEUTRAL)
        if mood < 0.35:
            text = rng.choice(GOOD) + " " + text
        elif mood > 0.93:
            text = rng.choice(BAD)
        name = eng[0]
        title = f"{brand} {name} {gen}, {year}" if brand != "Audi" else f"{brand} {model} {name}, {year}"
        if brand == "Mercedes-Benz":
            title = f"{brand} {name} {gen}, {year}"
        if brand == "BMW" and model.startswith("X"):
            title = f"{brand} {model} {name} {gen}, {year}"
        phone_hash = hashlib.md5(f"{sid}".encode()).hexdigest()[:10]
        desc = f"{text} Пробег {km:,} км, {trans}, {eng[1]} {eng[2]}, {drive} привод.".replace(",", " ")
        r = RawListing(
            source=self.name, source_id=sid, url=f"https://demo.autohunter.local/car/{sid}", title=title,
            description=desc, price=price, posted_at=posted_at, city=city, region=region if structured else None,
            seller_type=seller, seller_key=f"s{phone_hash}", photos=[], is_demo=True,
        )
        if structured:
            r.year, r.mileage, r.engine_volume, r.power_hp = year, km, eng[1], eng[3]
            r.fuel, r.transmission, r.drive, r.body = eng[2], trans, drive, body
            r.brand, r.model = brand, model
        else:
            r.brand = brand  # остальное нормализатор достанет из текста
        return r

    def _bootstrap(self) -> list[RawListing]:
        rng = random.Random(self.seed)
        now = utcnow()
        items = []
        for i in range(self.initial):
            posted = now - timedelta(minutes=rng.uniform(5, 60 * 24 * 14))
            items.append(self._make(rng, f"demo-{i}", posted, structured=rng.random() < 0.6))
        # несколько пар-дублей (одна и та же машина, повторная публикация другим продавцом/ID)
        for k in range(min(8, max(0, (len(items) - 3) // 11))):
            src = items[k * 11 + 3]
            dup = src.model_copy(update={
                "source_id": f"demo-dup-{k}", "url": f"https://demo.autohunter.local/car/demo-dup-{k}",
                "price": int(src.price * 0.98), "posted_at": now - timedelta(hours=k + 1)})
            items.append(dup)
        return items

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        cursor = dict(ctx.cursor)
        out: list[RawListing] = []
        if not cursor.get("bootstrapped"):
            out += self._bootstrap()
            cursor["bootstrapped"] = True
        if self.live:
            self._polls += 1
            n = self._rng.choices([0, 1, 2], weights=[3, 4, 2])[0]
            now = utcnow()
            for _ in range(n):
                cursor["n"] = cursor.get("n", 0) + 1
                posted = now - timedelta(seconds=self._rng.uniform(2, 25))
                item = self._make(self._rng, f"demo-live-{cursor['n']}", posted, structured=self._rng.random() < 0.6)
                self._live_items.append(item)
                out.append(item)
            if self._polls % 4 == 0 and self._live_items:  # снижение цены у ранее найденного
                old = self._rng.choice(self._live_items)
                old.price = int(old.price * self._rng.uniform(0.88, 0.95) / 1000) * 1000
                out.append(old)
        return FetchResult(out, cursor)
