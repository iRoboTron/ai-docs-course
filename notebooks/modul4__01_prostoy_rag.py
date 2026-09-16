# %% [markdown]
# # Лаборатория 4. v4: простой RAG
#
# **Что мы сделаем:** перестанем отправлять модели весь сайт. Научимся превращать HTML
# в текст, резать его на куски, находить нужные куски по вопросу и отправлять только их.
#
# | Шаг | Что делаем | Кто пишет |
# |---|---|---|
# | 1 | Подключаемся, берём страницы сайта как HTML | дано |
# | 2 | HTML → текст: что выкидываем и почему | пишем вместе |
# | 3 | Режем текст на куски | пишем вместе |
# | 4 | Поиск по словам: находим нужный кусок | пишем вместе |
# | 5 | v4: RAG целиком, замер на журнале случаев | пишем вместе |
# | 6 | v3 против v4: цена, время, точность | дано |
# | 7 | Разбор провала под лупой | дано |
# | 8 | Размечаем эталон для модуля 5 | пишем вместе |
# | 9 | Задания | пиши сам |
#
# **Запросов к модели:** около 20 — RAG заметно дешевле v3.

# %%
!pip -q install openai

# %% [markdown]
# ## Шаг 1. Подключаемся и берём сайт `[дано]`
#
# В прошлом модуле текст сайта был уже очищен. Теперь возьмём его как есть — в HTML,
# с меню, футером и тегами: именно так выглядят настоящие страницы.

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
        print(f"Подключились. Адрес: {BASE_URL}, модель: {MODEL}")
    except Exception as oshibka:
        print(f"Не подошло: {type(oshibka).__name__} — {str(oshibka)[:120]}")
        API_KEY = None

CENA_VHODA, CENA_VYHODA = 0.03, 0.13

# %%
BAZA = "https://raw.githubusercontent.com/iRoboTron/ai-docs-course/main/fixtures/site/"
IMENA = ["index.html", "uslugi.html", "garantiya.html", "dostavka.html", "kontakty.html"]

STRANICY_HTML = {}
for imya in IMENA:
    with urllib.request.urlopen(BAZA + imya, timeout=30) as otvet:
        STRANICY_HTML[imya] = otvet.read().decode("utf-8")

print(f"Скачано страниц: {len(STRANICY_HTML)}")
print(f"Всего символов HTML: {sum(len(s) for s in STRANICY_HTML.values())}\n")
print("Начало страницы uslugi.html как есть:")
print(STRANICY_HTML["uslugi.html"][:400])

# %% [markdown]
# **Что посмотреть в выводе:** половина текста — теги, меню и футер. Если отправить это
# модели как есть, мы заплатим за разметку и за одно и то же меню на каждой странице.

# %% [markdown]
# ## Шаг 2. HTML → текст `[пишем вместе]`
#
# Нужен чистый текст. Полноценные библиотеки (`beautifulsoup4`, `trafilatura`) делают это
# лучше, но здесь важно понять принцип, поэтому напишем простую очистку сами.
#
# Что делаем по шагам: выкидываем `script` и `style` вместе с содержимым, выкидываем
# навигацию и футер, снимаем оставшиеся теги, приводим пробелы в порядок.

# %%
def html_v_tekst(stranica):
    tekst = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", stranica)
    tekst = re.sub(r"(?is)<(h[1-6]|p|li|br|div|tr)[^>]*>", "\n", tekst)   # блоки — с новой строки
    tekst = re.sub(r"(?s)<[^>]+>", " ", tekst)                            # остальные теги убираем
    tekst = html.unescape(tekst)
    stroki = [s.strip() for s in tekst.splitlines()]
    return "\n".join(s for s in stroki if s)


STRANICY = {imya: html_v_tekst(kod) for imya, kod in STRANICY_HTML.items()}

for imya in IMENA[:2]:
    bylo, stalo = len(STRANICY_HTML[imya]), len(STRANICY[imya])
    print(f"{imya:<16} {bylo:>5} → {stalo:>5} символов (осталось {stalo / bylo:.0%})")

print("\nТак теперь выглядит uslugi.html:\n")
print(STRANICY["uslugi.html"][:500])

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Текст ужался примерно вдвое: при подготовке лаборатории страница услуг похудела
#    с 1304 до 727 символов. И это маленькие учебные страницы — на настоящем сайте
#    с вёрсткой и скриптами разница больше в разы.
# 2. Проверьте глазами: не выкинули ли лишнего? Очистка — то место, где легко потерять
#    таблицу с ценами и не заметить.
# 3. Мы выкинули `nav` и `footer` намеренно: меню повторяется на каждой странице и
#    только мешает поиску.

# %% [markdown]
# ## Шаг 3. Режем на куски `[пишем вместе]`
#
# Отправлять страницу целиком — снова расточительно: в вопросе про гарантию не нужен
# прайс на кофемашины. Поэтому текст режут на куски.
#
# Простейший способ — по абзацам, с ограничением по длине. Заголовок страницы добавляем
# к каждому куску: без него кусок «от 4900 ₽, срок 1–2 дня» непонятен ни человеку,
# ни поиску.

# %%
MAX_SIMVOLOV = 400


def narezat(imya, tekst):
    zagolovok = tekst.splitlines()[0] if tekst else imya
    kuski, tekushchiy = [], ""
    for abzac in tekst.split("\n"):
        if len(tekushchiy) + len(abzac) > MAX_SIMVOLOV and tekushchiy:
            kuski.append(tekushchiy.strip())
            tekushchiy = ""
        tekushchiy += abzac + "\n"
    if tekushchiy.strip():
        kuski.append(tekushchiy.strip())
    return [{"stranica": imya, "zagolovok": zagolovok, "tekst": f"[{zagolovok}] {k}"} for k in kuski]


KUSKI = [k for imya, tekst in STRANICY.items() for k in narezat(imya, tekst)]

print(f"Кусков всего: {len(KUSKI)}")
print(f"Средняя длина: {sum(len(k['tekst']) for k in KUSKI) // len(KUSKI)} символов\n")
for nomer, kusok in enumerate(KUSKI[:3]):
    print(f"--- кусок {nomer} ({kusok['stranica']}) ---")
    print(kusok["tekst"][:220], "…\n")

# %% [markdown]
# **Что посмотреть в выводе:** при подготовке лаборатории вышло 11 кусков средней длиной
# 334 символа, и каждый начинается с заголовка страницы. Это уже пригодная еда для поиска.
#
# Хороший ли это способ нарезки — вопрос открытый: можно резать по заголовкам, по смыслу,
# с перекрытием. В модуле 5 мы сравним варианты по числам, а пока берём самый простой.

# %% [markdown]
# ## Шаг 4. Поиск по словам `[пишем вместе]`
#
# Теперь по вопросу нужно найти подходящие куски. Начнём с самого простого поиска:
# считаем, сколько слов вопроса встретилось в куске.
#
# Одна тонкость: «подшипников» и «подшипники» — для компьютера разные слова. Поэтому
# слова грубо обрезаем до первых шести букв. Это дешёвая замена настоящей морфологии.

# %%
def v_slova(tekst):
    return {s[:6] for s in re.findall(r"[а-яёa-z0-9]+", tekst.lower()) if len(s) > 2}


def nayti(vopros, skolko=3, podrobno=False):
    slova_voprosa = v_slova(vopros)
    ocenki = []
    for nomer, kusok in enumerate(KUSKI):
        obshchie = slova_voprosa & v_slova(kusok["tekst"])
        if obshchie:
            ocenki.append((len(obshchie), nomer, obshchie))
    ocenki.sort(reverse=True)
    if podrobno:
        print(f"Вопрос: {vopros}")
        print(f"Слова вопроса: {sorted(slova_voprosa)}")
        for ball, nomer, obshchie in ocenki[:5]:
            print(f"   {ball} совпадений, кусок {nomer} ({KUSKI[nomer]['stranica']}): {sorted(obshchie)}")
            print(f"      {KUSKI[nomer]['tekst'][:110]}…")
    return [KUSKI[nomer] for _, nomer, _ in ocenki[:skolko]]


nayti("Сколько стоит замена подшипников в стиральной машине?", podrobno=True)

# %% [markdown]
# **Что посмотреть в выводе:** видно не только какие куски нашлись, но и **почему** —
# по каким именно словам. Это и есть трасса поиска: когда бот ответит неправильно, первым
# делом смотрят сюда.

# %% [markdown]
# ## Шаг 5. v4: собираем RAG `[пишем вместе]`
#
# Теперь всё вместе. Схема простая и от версии к версии не меняется:
#
# вопрос → найти куски → положить только их в запрос → ответить только по ним.
#
# Важная деталь: если поиск не нашёл ничего, модель **не зовём вообще** — отвечаем отказом
# сами. Это бесплатно и надёжнее любой просьбы.

# %%
PRAVILA_V4 = """Ты помощник сервисного центра «Полярис».
Отвечай ТОЛЬКО по тексту из блока ДАННЫЕ. Если ответа там нет — ответь ровно:
«Не знаю, уточните у оператора». Отвечай кратко, одно-два предложения."""

SLUCHAI = [
    {"id": "subbota", "vopros": "Во сколько вы закрываетесь в субботу?", "zhdem": "17:00"},
    {"id": "garantiya", "vopros": "Какая у вас гарантия на ремонт?", "zhdem": "12 месяц"},
    {"id": "podshipniki", "vopros": "Сколько стоит замена подшипников в стиральной машине?", "zhdem": "4900"},
    {"id": "samokaty", "vopros": "Вы чините электросамокаты?", "zhdem": "не знаю"},
    {"id": "diagnostika", "vopros": "Диагностика платная?", "zhdem": "1200"},
    {"id": "kurer", "vopros": "Сколько стоит курьер туда и обратно?", "zhdem": "1200"},
    {"id": "hranenie", "vopros": "Сколько стоит хранение после ремонта?", "zhdem": "100"},
]


def sprosit(soobshcheniya, max_tokens=150):
    nachalo = time.perf_counter()
    otvet = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens, messages=soobshcheniya)
    usage = otvet.usage
    stoimost = (usage.prompt_tokens * CENA_VHODA + usage.completion_tokens * CENA_VYHODA) / 1e6
    return ((otvet.choices[0].message.content or "").strip(), usage,
            time.perf_counter() - nachalo, stoimost)


def bot_v4(vopros, skolko=3):
    naydeno = nayti(vopros, skolko=skolko)
    if not naydeno:
        return "Не знаю, уточните у оператора.", None, 0.0, 0.0   # модель не зовём
    dannye = "\n\n".join(k["tekst"] for k in naydeno)
    return sprosit([{"role": "system", "content": PRAVILA_V4},
                    {"role": "user", "content": f"ДАННЫЕ:\n{dannye}\n\nВОПРОС: {vopros}"}])


def proverit(otvet, zhdem):
    nizhniy = otvet.lower()
    if zhdem == "не знаю":
        return any(s in nizhniy for s in ("не зна", "уточните", "нет информац"))
    return zhdem.lower() in nizhniy


print(f"{'':2} {'случай':<12} {'вход':>6} {'цена':>10}  ответ")
verno_v4, vhod_v4, cena_v4 = 0, 0, 0.0
for sluchay in SLUCHAI:
    otvet, usage, sekundy, stoimost = bot_v4(sluchay["vopros"])
    ok = proverit(otvet, sluchay["zhdem"])
    verno_v4 += ok
    vhod_v4 += usage.prompt_tokens if usage else 0
    cena_v4 += stoimost
    print(f"{'✅' if ok else '❌'} {sluchay['id']:<12} {usage.prompt_tokens if usage else 0:>6} "
          f"{stoimost:>10.6f}  {otvet[:60]}")
print(f"\nv4: верных {verno_v4} из {len(SLUCHAI)}, вход всего {vhod_v4} токенов, ${cena_v4:.6f}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Колонка «вход» — в разы меньше, чем у v3: в запрос едут три куска, а не весь сайт.
#    При подготовке лаборатории вышло от 227 до 523 токенов на вопрос против 1200 у v3.
# 2. Случай `samokaty` отвечен **без запроса к модели**: вход 0, цена 0. Поиск ничего
#    не нашёл, и код ответил сам — бесплатно и мгновенно.
# 3. А вот случай `garantiya` при подготовке **провалился**: бот ответил про сроки выезда
#    мастера, а не про 12 месяцев. Поиск принёс не тот кусок. Не спешите чинить наугад —
#    сначала трасса (шаг 7).

# %% [markdown]
# ## Шаг 6. v3 против v4 `[дано]`
#
# Сравним честно: те же вопросы, та же модель, разница только в том, что уходит в запрос.

# %%
VES_SAYT = "\n\n".join(f"=== {imya} ===\n{tekst}" for imya, tekst in STRANICY.items())
PRAVILA_V3 = PRAVILA_V4 + "\n\nДАННЫЕ:\n" + VES_SAYT


def bot_v3(vopros):
    return sprosit([{"role": "system", "content": PRAVILA_V3}, {"role": "user", "content": vopros}])


verno_v3, vhod_v3, cena_v3, vremya_v3 = 0, 0, 0.0, 0.0
for sluchay in SLUCHAI:
    otvet, usage, sekundy, stoimost = bot_v3(sluchay["vopros"])
    verno_v3 += proverit(otvet, sluchay["zhdem"])
    vhod_v3 += usage.prompt_tokens
    cena_v3 += stoimost
    vremya_v3 += sekundy

print(f"{'версия':<6} {'верных':>8} {'вход':>8} {'цена прогона':>14} {'на 100 000 вопросов':>20}")
for nazvanie, verno, vhod, cena_progona in (("v3", verno_v3, vhod_v3, cena_v3),
                                            ("v4", verno_v4, vhod_v4, cena_v4)):
    na_vopros = cena_progona / len(SLUCHAI)
    print(f"{nazvanie:<6} {f'{verno} из {len(SLUCHAI)}':>8} {vhod:>8} {cena_progona:>14.6f} "
          f"{na_vopros * 100_000:>19.2f}$")
print(f"\nRAG дешевле в {vhod_v3 / max(vhod_v4, 1):.1f} раза по входным токенам")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **Цена** упала в разы: при подготовке лаборатории 8297 входных токенов у v3 против
#    2137 у v4 — дешевле в 3,9 раза. И разрыв будет тем больше, чем больше сайт: у v3 вход
#    растёт вместе с сайтом, у v4 не растёт вовсе.
# 2. **Точность упала**: 7 из 7 у v3 против 6 из 7 у v4. Потерялся вопрос про гарантию —
#    поиск не принёс нужный кусок.
# 3. Вот честный размен RAG: **в 4 раза дешевле ценой одного проваленного вопроса**.
#    Никто не обещал, что новая версия лучше по всем колонкам сразу. Дальше есть выбор:
#    смириться, чинить поиск (модуль 5) или отправлять больше кусков.

# %% [markdown]
# ## Шаг 7. Разбор провала под лупой `[дано]`
#
# Когда бот ошибается, вопрос всегда один: **виноват поиск или модель?** Ответ виден
# из трассы.

# %%
def razobrat(vopros, zhdem):
    naydeno = nayti(vopros, podrobno=True)
    otvet, *_ = bot_v4(vopros)
    print(f"\n   Ответ бота: {otvet}")
    if not naydeno:
        print("   Вывод: ПОИСК ничего не нашёл — модель даже не звали.")
    elif any(zhdem.lower() in k["tekst"].lower() for k in naydeno):
        ok = proverit(otvet, zhdem)
        print(f"   Вывод: нужный факт был в найденном. {'Модель ответила верно.' if ok else 'Виновата МОДЕЛЬ или правила.'}")
    else:
        print("   Вывод: ПОИСК принёс не те куски — нужного факта в них нет.")


razobrat("У вас можно оплатить картой?", "не знаю")
print("\n" + "=" * 70 + "\n")
razobrat("Почём поменять компрессор в холодильнике?", "8700")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Первый вопрос — про оплату картой. Ответа на сайте нет; при подготовке лаборатории
#    поиск принёс куски про приём техники, а бот честно отказался. Правильное поведение.
# 2. Второй вопрос задан другими словами: на сайте «замена компрессора», гость спрашивает
#    «почём поменять». Совпало только два слова из четырёх — но этого хватило, нужный кусок
#    нашёлся, и ответ верный. С «гарантией» из шага 5 так не повезло.
# 3. Так выглядит главный инструмент отладки RAG. Без трассы остаётся гадать, а с ней
#    сразу видно, какую половину чинить.

# %% [markdown]
# ## Шаг 8. Размечаем эталон `[пишем вместе]`
#
# В модуле 5 мы будем сравнивать варианты поиска, и для этого нужно знать, **какой кусок
# считается правильным** для каждого вопроса. Разметим это сейчас, пока куски перед глазами.
#
# Способ — полуавтоматический: код предлагает кандидатов по ожидаемому ответу, человек
# смотрит и подтверждает. Так делают и на настоящих проектах: модель или эвристика
# предлагает, человек проверяет.

# %%
ETALON = []
for sluchay in SLUCHAI:
    zhdem = sluchay["zhdem"]
    if zhdem == "не знаю":
        nuzhnye = []
    else:
        nuzhnye = [nomer for nomer, kusok in enumerate(KUSKI) if zhdem.lower() in kusok["tekst"].lower()]
    ETALON.append({**sluchay, "nuzhnye_kuski": nuzhnye})
    print(f"{sluchay['id']:<12} ждём «{zhdem:<10}» → куски {nuzhnye}")
    for nomer in nuzhnye[:2]:
        print(f"                 {nomer}: {KUSKI[nomer]['tekst'][:90]}…")

print("\nПроверьте глазами: правда ли в этих кусках есть ответ? Если кусков слишком много,")
print("значит, ожидаемая строка слишком общая — например, «1200» встречается и в цене")
print("диагностики, и в цене курьера. Такой случай стоит уточнить.")

# %% [markdown]
# ## Шаг 9. Задания `[пиши сам]`
#
# 1. **Сломайте очистку.** Уберите `nav` и `footer` из списка выкидываемых тегов в
#    `html_v_tekst` и перезапустите шаги 2–5. Что стало с числом кусков и с поиском?
# 2. **Размер куска.** Поставьте `MAX_SIMVOLOV = 150` и `MAX_SIMVOLOV = 1200`, каждый раз
#    заново собирая `KUSKI`. Что происходит с точностью ответов и с ценой?
# 3. **Сколько кусков отправлять.** В `bot_v4` поменяйте `skolko` на 1 и на 6. Где
#    выигрыш, где проигрыш?
# 4. **Свой трудный вопрос.** Придумайте вопрос, ответ на который есть на сайте, но
#    сформулирован другими словами. Найдёт ли его поиск? Добавьте случай в `SLUCHAI`.
#
# ## Что записать в файлы курса
#
# **`decisions.md`:**
#
# > **Что сравнивали.** v3 (весь сайт в запросе) и v4 (RAG: три куска) на одних вопросах.
# > **Числа.** Верных ответов: столько-то против столько-то. Входных токенов: столько-то
# > против столько-то, то есть RAG дешевле в N раз.
# > **Что выбрали.** v4: цена не растёт вместе с сайтом.
# > **Чем пожертвовали.** Появилось новое место поломки — поиск; часть вопросов теперь
# > проваливается не из-за модели, а из-за того, что кусок не нашёлся.
# > **Когда пересмотреть.** Если доля провалов поиска окажется выше, чем выгода по цене.
#
# **`cases.jsonl`** — добавьте случаи из заданий 4 и из шага 7 вместе с разметкой
# «какой кусок правильный»: он понадобится в модуле 5.
#
# ## Что унести с собой
#
# * HTML нужно чистить: меню и футер только мешают и стоят денег.
# * Куски режут с запасом смысла: заголовок страницы добавляют к каждому куску.
# * Поиск по словам спотыкается на формах слов — обрезка до основы это частично лечит.
# * Если поиск ничего не нашёл, честный отказ даёт **код**, а не модель: бесплатно и надёжно.
# * У RAG появляется новая точка отказа: теперь ошибка может быть в поиске, и первым делом
#   смотрят трассу.
