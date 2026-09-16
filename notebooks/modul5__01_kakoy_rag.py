# %% [markdown]
# # Лаборатория 5. v5: какой RAG выбрать
#
# **Что мы сделаем:** перестанем гадать. Сравним варианты нарезки и поиска на одних и тех
# же данных и вопросах, посчитаем метрики и запишем решение в журнал.
#
# Правило сравнения: **меняем один фактор за раз**. Сначала выбираем нарезку при
# фиксированном поиске, потом поиск при выбранной нарезке, потом число кусков.
#
# | Шаг | Что делаем | Кто пишет |
# |---|---|---|
# | 1 | Готовим данные и эталон | дано |
# | 2 | Метрики поиска: Hit@k и MRR | пишем вместе |
# | 3 | Фактор 1: нарезка | пишем вместе |
# | 4 | Фактор 2: поиск — слова, смысл, гибрид | пишем вместе |
# | 5 | Фактор 3: сколько кусков отправлять | пишем вместе |
# | 6 | Проверяем выбор ответами модели | дано |
# | 7 | Итоговая таблица и запись в decisions.md | дано |
# | 8 | Задания | пиши сам |
#
# **Запросов к модели:** около 15 — почти все замеры здесь бесплатные, поиск считается
# локально. Эмбеддинги тоже локальные: модель скачается один раз (около 500 МБ).

# %%
!pip -q install openai sentence-transformers rank_bm25

# %% [markdown]
# ## Шаг 1. Данные и эталон `[дано]`
#
# Берём тот же сайт «Поляриса» и тот же набор вопросов. Для каждого вопроса известна
# строка, которая обязана быть в правильном ответе, — по ней мы размечаем, какой кусок
# считается нужным.

# %%
import getpass
import html
import os
import re
import time
import urllib.request

from openai import OpenAI


def iz_sekretov(imya, po_umolchaniyu=None):
    try:
        from google.colab import userdata
        znachenie = userdata.get(imya)
        if znachenie:
            return znachenie
    except Exception:
        pass
    return os.environ.get(imya) or po_umolchaniyu


BASE_URL = iz_sekretov("AI_BASE_URL", "https://ai9.adelfos.ru/api/v1")
MODEL = iz_sekretov("AI_MODEL", "qwen/qwen3.7-flash")
API_KEY = iz_sekretov("AI_KEY")

client = None
while client is None:
    if not API_KEY:
        API_KEY = getpass.getpass("Ключ или код доступа: ")
    probnyy = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=60, max_retries=0)
    try:
        probnyy.models.list()
        client = probnyy
        print(f"Подключились. Модель: {MODEL}")
    except Exception as oshibka:
        print(f"Не подошло: {type(oshibka).__name__} — {str(oshibka)[:120]}")
        API_KEY = None

BAZA = "https://raw.githubusercontent.com/iRoboTron/ai-docs-course/main/fixtures/site/"
IMENA = ["index.html", "uslugi.html", "garantiya.html", "dostavka.html", "kontakty.html"]


def html_v_tekst(stranica):
    tekst = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", stranica)
    tekst = re.sub(r"(?is)<(h[1-6]|p|li|br|div|tr)[^>]*>", "\n", tekst)
    tekst = re.sub(r"(?s)<[^>]+>", " ", tekst)
    tekst = html.unescape(tekst)
    return "\n".join(s.strip() for s in tekst.splitlines() if s.strip())


STRANICY = {}
for imya in IMENA:
    with urllib.request.urlopen(BAZA + imya, timeout=30) as otvet:
        STRANICY[imya] = html_v_tekst(otvet.read().decode("utf-8"))

VOPROSY = [
    {"id": "subbota", "vopros": "Во сколько вы закрываетесь в субботу?", "zhdem": "17:00"},
    {"id": "garantiya", "vopros": "Какая у вас гарантия на ремонт?", "zhdem": "12 месяцев"},
    {"id": "podshipniki", "vopros": "Сколько стоит замена подшипников?", "zhdem": "4900"},
    {"id": "kompressor", "vopros": "Почём поменять компрессор в холодильнике?", "zhdem": "8700"},
    {"id": "kurer", "vopros": "Сколько стоит курьер туда и обратно?", "zhdem": "1200 ₽ туда и обратно"},
    {"id": "hranenie", "vopros": "Сколько стоит хранение техники после ремонта?", "zhdem": "100 ₽ за день"},
    {"id": "otsrochka", "vopros": "Какая отсрочка платежа для организаций?", "zhdem": "10 рабочих дней"},
    {"id": "voda", "vopros": "Гарантия действует, если технику залили водой?", "zhdem": "попаданием воды"},
    {"id": "srochno", "vopros": "Можно вызвать мастера сегодня же?", "zhdem": "900"},
    {"id": "plata", "vopros": "У вас можно оплатить картой?", "zhdem": None},
]
print(f"Страниц: {len(STRANICY)}, вопросов в эталоне: {len(VOPROSY)}, "
      f"из них без ответа на сайте: {sum(1 for v in VOPROSY if v['zhdem'] is None)}")

# %% [markdown]
# ## Шаг 2. Метрики поиска `[пишем вместе]`
#
# Прежде чем сравнивать, нужно договориться, что считать успехом. Для поиска есть две
# простые метрики.
#
# > **Hit@k** — доля вопросов, для которых нужный кусок попал в первые k найденных.
# > Отвечает на вопрос «нашли ли вообще».
#
# > **MRR** (средний обратный ранг) — среднее от 1 делить на позицию первого нужного куска.
# > Нужный кусок на первом месте даёт 1, на втором — 0,5, на третьем — 0,33. Отвечает
# > на вопрос «насколько высоко нашли».
#
# Зачем обе: Hit@3 не различает «нужный кусок был первым» и «еле влез третьим», а для цены
# это важно — чем выше нужный кусок, тем меньше кусков можно отправлять модели.

# %%
def razmetit(kuski):
    """Для каждого вопроса отмечает номера кусков, где есть ожидаемая строка."""
    razmetka = {}
    for vopros in VOPROSY:
        if vopros["zhdem"] is None:
            razmetka[vopros["id"]] = []
        else:
            razmetka[vopros["id"]] = [n for n, k in enumerate(kuski)
                                      if vopros["zhdem"].lower() in k["tekst"].lower()]
    return razmetka


def ocenit_poisk(nayti_func, kuski, k=3):
    """Считает Hit@k и MRR по эталону. Возвращает (hit, mrr, провалы)."""
    razmetka = razmetit(kuski)
    popalo, summa_rangov, provaly = 0, 0.0, []
    for vopros in VOPROSY:
        nuzhnye = razmetka[vopros["id"]]
        naydeno = nayti_func(vopros["vopros"], k)
        if not nuzhnye:                       # правильное поведение — не найти ничего
            uspeh = len(naydeno) == 0
            popalo += uspeh
            summa_rangov += 1.0 if uspeh else 0.0
            if not uspeh:
                provaly.append((vopros["id"], "нашлось лишнее", naydeno[:3]))
            continue
        pozicii = [i + 1 for i, nomer in enumerate(naydeno) if nomer in nuzhnye]
        if pozicii:
            popalo += 1
            summa_rangov += 1 / pozicii[0]
        else:
            provaly.append((vopros["id"], f"нужны {nuzhnye}", naydeno[:3]))
    return popalo / len(VOPROSY), summa_rangov / len(VOPROSY), provaly

# %% [markdown]
# ## Шаг 3. Фактор 1: нарезка `[пишем вместе]`
#
# Три способа порезать один и тот же текст. Поиск на этом шаге фиксирован — обычный поиск
# по словам, тот же, что в модуле 4.

# %%
def narezka_po_razmeru(max_simvolov=400):
    kuski = []
    for imya, tekst in STRANICY.items():
        zagolovok = tekst.splitlines()[0]
        tekushchiy = ""
        for abzac in tekst.split("\n"):
            if len(tekushchiy) + len(abzac) > max_simvolov and tekushchiy:
                kuski.append({"stranica": imya, "tekst": f"[{zagolovok}] {tekushchiy.strip()}"})
                tekushchiy = ""
            tekushchiy += abzac + "\n"
        if tekushchiy.strip():
            kuski.append({"stranica": imya, "tekst": f"[{zagolovok}] {tekushchiy.strip()}"})
    return kuski


def narezka_po_abzacam():
    return [{"stranica": imya, "tekst": f"[{tekst.splitlines()[0]}] {abzac.strip()}"}
            for imya, tekst in STRANICY.items()
            for abzac in tekst.split("\n") if len(abzac.strip()) > 40]


def narezka_po_zagolovkam():
    """Заголовки на страницах короткие и без точки — режем по ним."""
    kuski = []
    for imya, tekst in STRANICY.items():
        stranica_zagolovok = tekst.splitlines()[0]
        tekushchiy, podzagolovok = "", stranica_zagolovok
        for stroka in tekst.split("\n")[1:]:
            pohozh_na_zagolovok = len(stroka) < 60 and not stroka.endswith((".", ":", "₽"))
            if pohozh_na_zagolovok and tekushchiy:
                kuski.append({"stranica": imya,
                              "tekst": f"[{stranica_zagolovok} / {podzagolovok}] {tekushchiy.strip()}"})
                tekushchiy, podzagolovok = "", stroka
            elif pohozh_na_zagolovok:
                podzagolovok = stroka
            else:
                tekushchiy += stroka + "\n"
        if tekushchiy.strip():
            kuski.append({"stranica": imya,
                          "tekst": f"[{stranica_zagolovok} / {podzagolovok}] {tekushchiy.strip()}"})
    return kuski


def v_slova(tekst):
    return {s[:6] for s in re.findall(r"[а-яёa-z0-9]+", tekst.lower()) if len(s) > 2}


def poisk_po_slovam(kuski):
    def nayti(vopros, k=3):
        slova = v_slova(vopros)
        ocenki = [(len(slova & v_slova(kusok["tekst"])), nomer) for nomer, kusok in enumerate(kuski)]
        ocenki = [(ball, nomer) for ball, nomer in ocenki if ball > 0]
        ocenki.sort(reverse=True)
        return [nomer for _, nomer in ocenki[:k]]
    return nayti


VARIANTY_NAREZKI = {
    "по размеру 400": narezka_po_razmeru(400),
    "по абзацам": narezka_po_abzacam(),
    "по заголовкам": narezka_po_zagolovkam(),
}

print(f"{'нарезка':<18} {'кусков':>7} {'средняя длина':>14} {'Hit@3':>7} {'MRR':>7}")
for nazvanie, kuski in VARIANTY_NAREZKI.items():
    hit, mrr, provaly = ocenit_poisk(poisk_po_slovam(kuski), kuski)
    srednyaya = sum(len(k["tekst"]) for k in kuski) // len(kuski)
    print(f"{nazvanie:<18} {len(kuski):>7} {srednyaya:>14} {hit:>7.0%} {mrr:>7.2f}")
    for ident, prichina, naydeno in provaly:
        print(f"{'':<18}   ✗ {ident}: {prichina}, нашлось {naydeno}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# При подготовке лаборатории вышло так:
#
# | Нарезка | Кусков | Средняя длина | Hit@3 | MRR |
# |---|---|---|---|---|
# | по размеру 400 | 11 | 334 | 70% | 0,58 |
# | по абзацам | 27 | 129 | 60% | 0,50 |
# | **по заголовкам** | 18 | 208 | **70%** | **0,65** |
#
# 1. **Hit@3 у двух вариантов одинаковый** — если смотреть только на него, выбрать нельзя.
#    Разводит их MRR: у нарезки по заголовкам нужный кусок стоит выше в списке. Вот зачем
#    нужны две метрики.
# 2. **Мелкая нарезка проиграла обеим.** Абзацы по 129 символов рвут смысл: цена оказалась
#    в одном куске, а условие — в другом.
# 3. Список провалов важнее числа. Заметьте, что `garantiya` и `srochno` не нашлись
#    **ни при какой нарезке**: дело не в ней, а в поиске — им займёмся в шаге 4.

# %% [markdown]
# ## Шаг 4. Фактор 2: поиск `[пишем вместе]`
#
# Нарезку фиксируем — берём ту, что победила в шаге 3 (если варианты равны, берём
# «по заголовкам»: у неё куски осмысленнее). Теперь сравниваем способы поиска.
#
# * **По словам** — то, что уже есть.
# * **BM25** — тот же поиск по словам, но с весами: редкое слово важнее частого.
# * **По смыслу** — эмбеддинги: текст превращается в вектор чисел, ищем ближайшие.
# * **Гибрид** — объединяем списки двух поисков по формуле обратных рангов (RRF).

# %%
LUCHSHAYA_NAREZKA = "по заголовкам"
KUSKI = VARIANTY_NAREZKI[LUCHSHAYA_NAREZKA]
print(f"Работаем с нарезкой «{LUCHSHAYA_NAREZKA}», кусков: {len(KUSKI)}")

from rank_bm25 import BM25Okapi

BM25 = BM25Okapi([[s[:6] for s in re.findall(r"[а-яёa-z0-9]+", k["tekst"].lower())] for k in KUSKI])


def poisk_bm25(vopros, k=3):
    slova = [s[:6] for s in re.findall(r"[а-яёa-z0-9]+", vopros.lower())]
    ocenki = BM25.get_scores(slova)
    poryadok = sorted(range(len(KUSKI)), key=lambda i: ocenki[i], reverse=True)
    return [i for i in poryadok[:k] if ocenki[i] > 0]


# %%
from sentence_transformers import SentenceTransformer, util

print("Скачиваем модель эмбеддингов (один раз, ~500 МБ)…")
EMB = SentenceTransformer("intfloat/multilingual-e5-small")
VEKTORY = EMB.encode([f"passage: {k['tekst']}" for k in KUSKI], normalize_embeddings=True)
print(f"Готово: {VEKTORY.shape[0]} векторов по {VEKTORY.shape[1]} чисел")


def poisk_po_smyslu(vopros, k=3, porog=0.80):
    vektor = EMB.encode(f"query: {vopros}", normalize_embeddings=True)
    blizost = util.cos_sim(vektor, VEKTORY)[0]
    poryadok = sorted(range(len(KUSKI)), key=lambda i: float(blizost[i]), reverse=True)
    return [i for i in poryadok[:k] if float(blizost[i]) >= porog]


def gibrid(vopros, k=3):
    """RRF: складываем обратные ранги из двух списков. Позиция важнее сырых оценок."""
    bally = {}
    for spisok in (poisk_bm25(vopros, k * 3), poisk_po_smyslu(vopros, k * 3)):
        for pozicia, nomer in enumerate(spisok, 1):
            bally[nomer] = bally.get(nomer, 0) + 1 / (60 + pozicia)
    return [nomer for nomer, _ in sorted(bally.items(), key=lambda p: p[1], reverse=True)[:k]]


POISKI = {
    "по словам": poisk_po_slovam(KUSKI),
    "BM25": poisk_bm25,
    "по смыслу": poisk_po_smyslu,
    "гибрид RRF": gibrid,
}

print(f"\n{'поиск':<14} {'Hit@3':>7} {'MRR':>7}  провалы")
rezultaty_poiska = {}
for nazvanie, poisk in POISKI.items():
    hit, mrr, provaly = ocenit_poisk(poisk, KUSKI)
    rezultaty_poiska[nazvanie] = (hit, mrr)
    print(f"{nazvanie:<14} {hit:>7.0%} {mrr:>7.2f}  {', '.join(p[0] for p in provaly) or '—'}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# При подготовке лаборатории:
#
# | Поиск | Hit@3 | MRR | Провалы |
# |---|---|---|---|
# | по словам | 70% | 0,65 | garantiya, srochno, plata |
# | BM25 | 70% | 0,60 | garantiya, srochno, plata |
# | **по смыслу** | **80%** | **0,73** | srochno, plata |
# | гибрид RRF | 80% | 0,68 | srochno, plata |
#
# 1. **Поиск по смыслу выиграл** и починил вопрос про гарантию — тот самый, что провалился
#    в модуле 4. Слова там совпадали не те, а смысл совпал.
# 2. **BM25 оказался не лучше простого счёта слов** по MRR. На корпусе из 18 кусков веса
#    редких слов просто не на чем разыграться: BM25 раскрывается на тысячах документов.
# 3. **Гибрид не выиграл у чистого смысла** — тоже 80%, но MRR ниже. Он подмешал наверх
#    куски от словесного поиска. Вывод: сложное решение нужно проверять, а не брать
#    по умолчанию, что «гибрид всегда лучше».
# 4. Вопрос `plata` («можно оплатить картой») проваливается у всех: ответа на сайте нет,
#    но поиск всё равно что-то приносит. У поиска по смыслу от этого спасает порог близости,
#    и в заданиях вы его подберёте.

# %% [markdown]
# ## Шаг 5. Фактор 3: сколько кусков отправлять `[пишем вместе]`
#
# Чем больше кусков в запросе, тем выше шанс, что ответ там есть, — и тем дороже запрос.
# Посмотрим, где перегиб.

# %%
LUCHSHIY_POISK = max(rezultaty_poiska, key=lambda n: (rezultaty_poiska[n][0], rezultaty_poiska[n][1]))
poisk = POISKI[LUCHSHIY_POISK]
print(f"Лучший поиск по шагу 4: «{LUCHSHIY_POISK}»\n")

print(f"{'кусков':>7} {'Hit@k':>7} {'MRR':>7} {'символов в запросе':>19}")
for k in (1, 2, 3, 5, 8):
    hit, mrr, _ = ocenit_poisk(poisk, KUSKI, k=k)
    simvolov = sum(len(KUSKI[n]["tekst"]) for v in VOPROSY for n in poisk(v["vopros"], k)) // len(VOPROSY)
    print(f"{k:>7} {hit:>7.0%} {mrr:>7.2f} {simvolov:>19}")

# %% [markdown]
# **Что посмотреть в выводе.** При подготовке лаборатории:
#
# | Кусков | Hit@k | MRR | Символов в запросе |
# |---|---|---|---|
# | 1 | 70% | 0,70 | 208 |
# | 2 | 70% | 0,70 | 377 |
# | **3** | **80%** | **0,73** | 478 |
# | 5 | 80% | 0,73 | 735 |
# | 8 | 90% | 0,75 | 1038 |
#
# Качество растёт ступеньками, а длина запроса — равномерно. Переход с 3 на 5 кусков
# не дал ничего и подорожал в полтора раза. Переход на 8 добавил 10 процентных пунктов
# ценой удвоения запроса — решайте сами, стоит ли; мы берём 3.

# %% [markdown]
# ## Шаг 6. Проверяем выбор ответами `[дано]`
#
# Метрики поиска — не цель. Цель — верные ответы гостю. Прогоним модель с выбранной
# связкой и посчитаем ответы.

# %%
PRAVILA = """Ты помощник сервисного центра «Полярис».
Отвечай ТОЛЬКО по тексту из блока ДАННЫЕ. Если ответа там нет — ответь ровно:
«Не знаю, уточните у оператора». Отвечай кратко, одно-два предложения."""

VYBRANO_KUSKOV = 3


def otvetit(vopros):
    nomera = poisk(vopros, VYBRANO_KUSKOV)
    if not nomera:
        return "Не знаю, уточните у оператора.", 0, 0.0
    dannye = "\n\n".join(KUSKI[n]["tekst"] for n in nomera)
    otvet = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=150,
        messages=[{"role": "system", "content": PRAVILA},
                  {"role": "user", "content": f"ДАННЫЕ:\n{dannye}\n\nВОПРОС: {vopros}"}])
    usage = otvet.usage
    return ((otvet.choices[0].message.content or "").strip(), usage.prompt_tokens,
            (usage.prompt_tokens * 0.03 + usage.completion_tokens * 0.13) / 1e6)


def proverit(otvet, zhdem):
    nizhniy = otvet.lower()
    if zhdem is None:
        return any(s in nizhniy for s in ("не зна", "уточните", "нет информац"))
    return zhdem.lower() in nizhniy


verno, vhod_vsego, cena_vsego = 0, 0, 0.0
for vopros in VOPROSY:
    otvet, vhod, cena = otvetit(vopros["vopros"])
    ok = proverit(otvet, vopros["zhdem"])
    verno += ok
    vhod_vsego += vhod
    cena_vsego += cena
    print(f"{'✅' if ok else '❌'} {vopros['id']:<12} {otvet[:70]}")

print(f"\nВерных ответов: {verno} из {len(VOPROSY)}")
print(f"Средний вход: {vhod_vsego // len(VOPROSY)} токенов, цена вопроса ${cena_vsego / len(VOPROSY):.6f}")

# %% [markdown]
# **Что посмотреть в выводе.** При подготовке лаборатории вышло 8 из 10 — и оба провала
# поучительные.
#
# **`srochno`** («можно вызвать мастера сегодня же») — честный провал поиска: нужный кусок
# про срочный выезд за 900 ₽ не нашёлся ни одним способом.
#
# **`kurer`** — а вот это провал **проверки, а не бота**. Бот ответил «Курьерская доставка
# туда и обратно стоит 1200 ₽» — абсолютно верно. Но мы ждали подстроку «1200 ₽ туда
# и обратно», а в ответе слова стоят в другом порядке. Проверка по вхождению строки
# не понимает языка.
#
# Запомните этот случай: метрика, которая называет верный ответ неверным, вредна вдвойне —
# по ней принимают решения. В модуле 6 мы займёмся проверками всерьёз.
#
# %% [markdown]
# ## Шаг 7. Итог `[дано]`

# %%
print(f"""Выбрано по числам:
  нарезка         {LUCHSHAYA_NAREZKA}
  поиск           {LUCHSHIY_POISK}
  кусков в запрос {VYBRANO_KUSKOV}
  ответы          {verno} из {len(VOPROSY)}
  вход на вопрос  {vhod_vsego // len(VOPROSY)} токенов

Это и есть запись для decisions.md. Важно: выбор сделан на ЭТОМ корпусе и ЭТИХ вопросах.
На другом сайте числа будут другими — и решение придётся пересматривать.""")

# %% [markdown]
# ## Шаг 8. Задания `[пиши сам]`
#
# 1. **Порог близости.** В `poisk_po_smyslu` порог 0,80. Поставьте 0,70 и 0,88 и
#    перезапустите шаг 4. Что происходит с вопросом «можно оплатить картой», на который
#    ответа нет? Найдите порог, при котором он проходит, а остальные не ломаются.
# 5. **Почините проверку.** Случай `kurer` провалился из-за порядка слов. Замените
#    проверку по подстроке на проверку по числу («1200» есть в ответе) или по набору слов.
#    Сколько теперь верных ответов?
# 2. **Свой трудный вопрос.** Добавьте в `VOPROSY` вопрос, заданный совсем другими словами
#    («сколько ждать, если деталь заказная»). Какой поиск его находит?
# 3. **Честное сравнение.** Прогоните шаг 4 с нарезкой «по абзацам» вместо «по заголовкам».
#    Меняется ли победитель? Почему нельзя выбирать поиск и нарезку одновременно?
# 4. **Цена гибрида.** Замерьте время поиска для BM25 и для гибрида (`time.perf_counter`).
#    Во сколько раз гибрид медленнее и окупается ли он на вашем наборе?
#
# ## Что записать в файлы курса
#
# **`decisions.md`** — три записи, по одной на фактор. Каждая по рубрике: что сравнивали,
# числа в таблице, что выбрали, чем пожертвовали, когда пересмотреть.
#
# **`antipatterns.md`** — что не сработало: например, поиск по смыслу без порога близости
# (всегда что-то находит, поэтому бот перестаёт честно отказываться).
#
# ## Что унести с собой
#
# * Меняем один фактор за раз — иначе непонятно, что дало результат.
# * **Hit@k** говорит «нашли ли», **MRR** — «насколько высоко»; нужны обе.
# * Поиск по словам спотыкается на других словах, поиск по смыслу — на вопросах без ответа.
# * Гибрид обычно лучший по качеству и худший по цене и сложности.
# * Число кусков выбирают там, где качество перестаёт расти, а цена растёт дальше.
# * Любой выбор сделан на конкретном корпусе: смена данных — повод пересчитать.
