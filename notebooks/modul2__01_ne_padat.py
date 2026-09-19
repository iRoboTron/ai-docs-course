# %% [markdown]
# # Лаборатория 2. v2: не падать и отвечать в нужном виде
#
# **Что мы сделаем:** сломаем бота пятью способами, научим его переживать поломки и
# заставим отвечать не свободным текстом, а строгой структурой, которую можно проверить
# кодом.
#
# | Шаг | Что делаем | Кто пишет |
# |---|---|---|
# | 1 | Подключаемся, повторяем v1 из модуля 1 | дано |
# | 2 | Пять настоящих поломок: 400, 401, 413, тайм-аут, обрыв ответа | дано |
# | 3 | Сортировщик ошибок: временная или постоянная | пишем вместе |
# | 4 | Повторы с растущей паузой, проверка на «обезьяне» | пишем вместе |
# | 5 | Ответ по схеме: JSON и проверка pydantic | пишем вместе |
# | 6 | Потоковый ответ | дано |
# | 7 | Собираем v2 и замеряем на журнале случаев | пишем вместе |
# | 8 | Задания | пиши сам |
#
# **Запросов к модели:** около 30.

# %%
!pip -q install openai pydantic

# %% [markdown]
# ## Шаг 1. Подключаемся и повторяем v1 `[дано]`
#
# Всё как в модуле 1: адрес и ключ из секретов Colab (`AI_BASE_URL`, `AI_KEY`), цикл
# запрашивает ключ, пока подключение не заработает.

# %%
import getpass
import json
import os
import random
import time

import openai
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError


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
    probnyy = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=30, max_retries=0)
    try:
        probnyy.models.list()
        client = probnyy
        print(f"Подключились. Адрес: {BASE_URL}, модель: {MODEL}")
    except Exception as oshibka:
        print(f"Не подошло: {type(oshibka).__name__} — {str(oshibka)[:120]}")
        API_KEY = None

# %% [markdown]
# `max_retries=0` здесь принципиально: библиотека умеет повторять запросы сама, но делает
# это молча. Нам нужно видеть каждую попытку, поэтому повторы напишем свои — в шаге 4.

# %%
PRAVILA = (
    "Ты помощник сервисного центра «Полярис»: ремонт бытовой техники. "
    "Отвечай вежливо и коротко, максимум два предложения, на русском языке."
)

# Журнал случаев из модуля 1: те же пять вопросов гостей.
SLUCHAI = [
    {"id": "subbota", "vopros": "Во сколько вы закрываетесь в субботу?", "zhdem": "17:00"},
    {"id": "garantiya", "vopros": "Какая у вас гарантия на ремонт?", "zhdem": "12 месяц"},
    {"id": "podshipniki", "vopros": "Сколько стоит замена подшипников в стиральной машине?", "zhdem": "4900"},
    {"id": "samokaty", "vopros": "Вы чините электросамокаты?", "zhdem": "не знаю"},
    {"id": "diagnostika", "vopros": "Диагностика платная?", "zhdem": "1200"},
]


def bot_v1(vopros):
    otvet = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=120,
        messages=[{"role": "system", "content": PRAVILA}, {"role": "user", "content": vopros}])
    return (otvet.choices[0].message.content or "").strip()


print("v1 жив:", bot_v1("Вы работаете в воскресенье?"))

# %% [markdown]
# ## Шаг 2. Пять настоящих поломок `[дано]`
#
# Пока мы работали при идеальной погоде. В жизни сервис модели — это чужой компьютер
# далеко в сети, и он подводит. Сломаем запрос пятью способами и посмотрим, **как именно
# выглядит каждая поломка в Python**: тип исключения, код ответа, текст.

# %%
def poprobovat(nazvanie, zapros):
    """Выполняет запрос и печатает результат или разбор ошибки вместо Traceback."""
    print(f"\n=== {nazvanie} ===")
    nachalo = time.perf_counter()
    try:
        otvet = zapros()
        vybor = otvet.choices[0]
        print(f"✅ за {time.perf_counter() - nachalo:.1f} с, finish_reason={vybor.finish_reason}")
        print(f"   текст: {(vybor.message.content or '')[:120]!r}")
        return otvet
    except Exception as e:
        print(f"❌ через {time.perf_counter() - nachalo:.1f} с: {type(e).__name__}")
        kod = getattr(e, "status_code", None)
        if kod is not None:
            print(f"   код ответа: {kod}")
        print(f"   текст: {str(e)[:160]}")
        return e


SOOBSHCHENIYA = [{"role": "user", "content": "Назови столицу Франции одним словом."}]
polomki = {}

polomki["модель не разрешена"] = poprobovat(
    "1. модель, которой нет в списке",
    lambda: client.chat.completions.create(model="openai/gpt-6-astra", messages=SOOBSHCHENIYA, max_tokens=20))

chuzhoy = OpenAI(base_url=BASE_URL, api_key="nevernyy-klyuch", max_retries=0)
polomki["неверный ключ"] = poprobovat(
    "2. неверный ключ",
    lambda: chuzhoy.chat.completions.create(model=MODEL, messages=SOOBSHCHENIYA, max_tokens=20))

polomki["запрос слишком длинный"] = poprobovat(
    "3. запрос длиннее допустимого",
    lambda: client.chat.completions.create(
        model=MODEL, max_tokens=20, messages=[{"role": "user", "content": "текст " * 12_000}]))

polomki["тайм-аут"] = poprobovat(
    "4. тайм-аут в полсекунды",
    lambda: client.with_options(timeout=0.5).chat.completions.create(
        model=MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "Расскажи подробно о ремонте стиральных машин, 200 слов."}]))

obryv = poprobovat(
    "5. ответ обрывается: max_tokens=12",
    lambda: client.chat.completions.create(
        model=MODEL, max_tokens=12,
        messages=[{"role": "user", "content": 'Перечисли 5 городов России в JSON: {"goroda": [...]}. Только JSON.'}]))

if not isinstance(obryv, Exception):
    try:
        json.loads(obryv.choices[0].message.content or "")
        print("   JSON разобрался")
    except json.JSONDecodeError as e:
        print(f"   JSON НЕ разобрался: {e}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **Первые три** поломки — это `400`, `401` и `413`. Повторять такой запрос бессмысленно:
#    он составлен неправильно, и через минуту будет та же ошибка.
# 2. **Тайм-аут** приходит **без кода ответа**: сервер ничего не прислал, мы просто перестали
#    ждать. Это временная беда — с нормальным тайм-аутом тот же запрос пройдёт.
# 3. **Пятая поломка самая коварная:** формально **успех**, зелёная галочка. Но
#    `finish_reason=length` означает, что ответ оборвали на полуслове, и JSON не разбирается.
#    Программа, которая проверяет только «упало или нет», покажет гостю мусор.
#
# Отсюда правило: **код 200 не значит «годный ответ»**. Проверять нужно и сам ответ.

# %% [markdown]
# ## Шаг 3. Сортировщик ошибок `[пишем вместе]`
#
# Главное умение — отличать «подожди и повтори» от «повторять бесполезно».

# %%
VREMENNYE_KODY = {429, 500, 502, 503, 504}


def razobrat(oshibka):
    """Возвращает (вид, код). Вид: временная / постоянная / не от сервиса."""
    if isinstance(oshibka, (openai.APITimeoutError, openai.APIConnectionError)):
        return "временная", "сеть или тайм-аут"
    kod = getattr(oshibka, "status_code", None)
    if kod in VREMENNYE_KODY:
        return "временная", kod
    if kod is not None:
        return "постоянная", kod
    return "не от сервиса", type(oshibka).__name__


print(f"{'поломка':<26} {'вид':<15} код")
for nazvanie, rezultat in polomki.items():
    if isinstance(rezultat, Exception):
        vid, kod = razobrat(rezultat)
        print(f"{nazvanie:<26} {vid:<15} {kod}")
vid, kod = razobrat(NameError("опечатка в коде"))
print(f"{'ошибка в нашем коде':<26} {vid:<15} {kod}")

# %% [markdown]
# **Что посмотреть в выводе:** последняя строка — `NameError`, обычная ошибка в **нашей**
# программе. Она не от сервиса, её нельзя ни повторять, ни прятать. Вот почему
# `except Exception: pass` в цикле повторов — плохая идея: он проглотит и опечатку тоже.

# %% [markdown]
# ## Шаг 4. Повторы с растущей паузой `[пишем вместе]`
#
# Временную ошибку пережидаем и повторяем. Три детали, каждая важна:
#
# * **лимит попыток** — цикл обязан закончиться;
# * **пауза растёт** — сервис перегружен, частые повторы добьют его окончательно;
# * **разброс паузы** — если у всех клиентов ошибка случилась одновременно, они не должны
#   повторить строго через секунду все разом.

# %%
def s_povtorami(sdelat_zapros, popytok=4, pauza=1.0, podrobno=True):
    for popytka in range(1, popytok + 1):
        try:
            rezultat = sdelat_zapros()
            if podrobno:
                print(f"   попытка {popytka}: ✅")
            return rezultat
        except Exception as oshibka:
            vid, kod = razobrat(oshibka)
            if podrobno:
                print(f"   попытка {popytka}: ❌ {kod} ({vid})")
            if vid != "временная" or popytka == popytok:
                raise
            zhdat = pauza * random.uniform(0.5, 1.5)
            if podrobno:
                print(f"              пауза {zhdat:.1f} с")
            time.sleep(zhdat)
            pauza *= 2


print("Постоянная ошибка — повторов быть не должно:")
try:
    s_povtorami(lambda: client.chat.completions.create(
        model="openai/gpt-6-astra", messages=SOOBSHCHENIYA, max_tokens=20))
except Exception as e:
    print(f"   сдались сразу: {type(e).__name__}")

# %% [markdown]
# Настоящие 429 и 503 случаются редко и не по заказу. Чтобы проверить защиту, ломают
# нарочно: **«обезьяна»** с заданной вероятностью притворяется, что сервис ответил ошибкой.

# %%
class PoddelnayaOshibka(Exception):
    def __init__(self, status_code):
        super().__init__(f"поддельная ошибка {status_code}")
        self.status_code = status_code


def s_obezyanoy(vopros, veroyatnost=0.5, kod=503):
    def zapros():
        if random.random() < veroyatnost:
            raise PoddelnayaOshibka(kod)
        return bot_v1(vopros)
    return zapros


random.seed(3)
print("\nОбезьяна ломает половину запросов:\n")
for nomer in range(1, 4):
    print(f"Вопрос {nomer}:")
    try:
        otvet = s_povtorami(s_obezyanoy("Вы чините кофемашины?"), popytok=4, pauza=0.4)
        print(f"   → {otvet[:70]}")
    except Exception as e:
        print(f"   → не получилось: {e}")

# %% [markdown]
# **Что посмотреть в выводе:** у одних вопросов сразу ✅, у других одна-две неудачи, пауза
# и успех. Гость при этом просто ждёт на секунду дольше. Постоянная ошибка, наоборот,
# не повторяется ни разу — ровно как задумано.

# %% [markdown]
# ## Шаг 5. Ответ по схеме `[пишем вместе]`
#
# Пока бот отвечает свободным текстом. Это удобно человеку и неудобно программе: из текста
# не вытащишь, уверен ли бот в ответе и откуда он его взял.
#
# Попросим модель отвечать **структурой**, а проверять её будем библиотекой `pydantic`:
# она превращает JSON в объект и ругается, если поля не те.

# %%
class OtvetBota(BaseModel):
    otvet: str = Field(description="ответ гостю, одно-два предложения")
    uveren: bool = Field(description="true, если ответ основан на точных данных")
    chego_ne_hvataet: str | None = Field(default=None, description="каких данных не хватило")


PRAVILA_JSON = (
    PRAVILA +
    ' Ответ возвращай строго в JSON: {"otvet": "...", "uveren": true/false, '
    '"chego_ne_hvataet": "..." или null}. Никакого текста вокруг JSON.'
)


def sprosit_strukturoy(vopros, podrobno=True):
    """Просим JSON, проверяем pydantic. Если формат сломан — один повтор с подсказкой."""
    soobshcheniya = [{"role": "system", "content": PRAVILA_JSON}, {"role": "user", "content": vopros}]
    for popytka in (1, 2):
        syroy = client.chat.completions.create(
            model=MODEL, temperature=0, max_tokens=200,
            messages=soobshcheniya, response_format={"type": "json_object"})
        tekst = (syroy.choices[0].message.content or "").strip()
        try:
            return OtvetBota.model_validate_json(tekst)
        except ValidationError as oshibka:
            if podrobno:
                print(f"   попытка {popytka}: формат не подошёл — {str(oshibka).splitlines()[0]}")
            if popytka == 2:
                raise
            soobshcheniya += [
                {"role": "assistant", "content": tekst},
                {"role": "user", "content": "Ответ не разобрался. Верни строго JSON с полями "
                                            "otvet, uveren, chego_ne_hvataet."},
            ]


for vopros in ("Во сколько вы закрываетесь в субботу?", "Вы чините электросамокаты?"):
    rezultat = sprosit_strukturoy(vopros)
    print(f"❓ {vopros}")
    print(f"   otvet: {rezultat.otvet}")
    print(f"   uveren: {rezultat.uveren}, чего не хватает: {rezultat.chego_ne_hvataet}\n")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Ответ теперь **объект**, а не текст: `rezultat.uveren` можно проверить кодом, не
#    вчитываясь в формулировку.
# 2. Поле `uveren` — это по-прежнему **мнение модели о себе**, а не факт. При подготовке
#    лаборатории модель ответила «Мы работаем до 18:00 в субботу» (на сайте 17:00)
#    и поставила `uveren: True`. То есть поле говорит «я уверена», а не «это правда».
# 3. `response_format={"type": "json_object"}` просит сервер отдать JSON, а `pydantic`
#    проверяет, что поля те самые. Просьба без проверки ничего не гарантирует.

# %% [markdown]
# ## Шаг 6. Потоковый ответ `[дано]`
#
# Гость на сайте ждёт ответ несколько секунд и смотрит в пустой экран. Поток отдаёт текст
# кусочками по мере написания: быстрее не становится, но ожидание переносится легче.

# %%
nachalo = time.perf_counter()
pervyy, kuski = None, []
potok = client.chat.completions.create(
    model=MODEL, temperature=0, max_tokens=200, stream=True,
    messages=[{"role": "system", "content": PRAVILA},
              {"role": "user", "content": "Расскажите, как у вас проходит ремонт: по шагам."}])
for kusok in potok:
    if not kusok.choices or not kusok.choices[0].delta.content:
        continue
    moment = time.perf_counter() - nachalo
    if pervyy is None:
        pervyy = moment
    kuski.append((moment, kusok.choices[0].delta.content))

print("Первые 8 кусочков:")
for moment, tekst in kuski[:8]:
    print(f"   {moment:5.2f} с  {tekst!r}")
print(f"\nвсего кусочков: {len(kuski)}")
print(f"первый текст через {pervyy:.2f} с, ответ дописан через {time.perf_counter() - nachalo:.2f} с")
print(f"\nСобранный ответ:\n{''.join(t for _, t in kuski)}")

# %% [markdown]
# **Что посмотреть в выводе:** первый кусочек приходит заметно раньше, чем готов весь ответ.
# Полное время при этом то же — поток не ускоряет модель.
#
# Важно: кусочки нарезаны как попало, границы слов не соблюдаются. Поэтому разбирать JSON
# по кусочку нельзя, сначала собираем текст целиком. Для ответов, которые читает программа,
# поток просто не нужен.

# %% [markdown]
# ## Шаг 7. Собираем v2 и замеряем `[пишем вместе]`
#
# Складываем всё вместе: тайм-аут, повторы только для временных ошибок, ответ по схеме,
# честное «не знаю» — если модель сама признала, что не уверена.

# %%
def bot_v2(vopros):
    """v2: не падает, отвечает структурой, неуверенный ответ превращает в отказ."""
    try:
        rezultat = s_povtorami(lambda: sprosit_strukturoy(vopros, podrobno=False),
                               popytok=3, pauza=0.5, podrobno=False)
    except Exception as oshibka:
        vid, _ = razobrat(oshibka)
        if vid == "временная":
            return "Сервис сейчас недоступен, попробуйте через минуту."
        return "Не получилось обработать вопрос, сообщите администратору сайта."
    if not rezultat.uveren:
        return "Не знаю точно, уточните у оператора."
    return rezultat.otvet


def proverit(otvet, zhdem):
    nizhniy = otvet.lower()
    if zhdem == "не знаю":
        return any(s in nizhniy for s in ("не зна", "уточните", "не уверен"))
    return zhdem.lower() in nizhniy


def progon(bot, nazvanie):
    print(f"=== {nazvanie} ===")
    verno = 0
    for sluchay in SLUCHAI:
        otvet = bot(sluchay["vopros"])
        ok = proverit(otvet, sluchay["zhdem"])
        verno += ok
        print(f"{'✅' if ok else '❌'} {sluchay['id']:<12} ждём «{sluchay['zhdem']}» | {otvet[:70]}")
    print(f"Верных ответов: {verno} из {len(SLUCHAI)}\n")
    return verno


verno_v1 = progon(bot_v1, "v1 из модуля 1")
verno_v2 = progon(bot_v2, "v2: повторы + схема ответа")
print(f"Было {verno_v1} из {len(SLUCHAI)}, стало {verno_v2} из {len(SLUCHAI)}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **Число верных ответов не выросло.** При подготовке лаборатории было 1 из 5 и стало
#    1 из 5 — ожидаемо: мы не дали боту ни одного факта о «Полярисе», а чинили надёжность.
# 2. Зато изменилось **поведение**: v2 не падает на ошибках сети, всегда отвечает
#    разбираемой структурой, а неуверенный ответ превращает в честный отказ.
# 3. И главное наблюдение: **отказов почти не было**. Модель ставила `uveren: True` даже
#    там, где выдумывала. «Уверена» — это про тон ответа, а не про наличие данных.
#    Поле `uveren` нельзя использовать как проверку: это самооценка, а не факт.
# 4. Побочный эффект схемы: ответы стали осторожнее по формулировке («гарантия от 6 до
#    12 месяцев», «стоимость вычитается из итоговой суммы»), но точнее не стали.
#
# Вывод для журнала решений: надёжность и знания — разные задачи, и вторая не решается
# ни повторами, ни схемой ответа. Ею займёмся в модуле 3.

# %% [markdown]
# ## Шаг 8. Задания `[пиши сам]`
#
# 1. **Сломайте повторы.** Поставьте в `s_obezyanoy` вероятность 0.9 и `popytok=4`. Сколько
#    вопросов не получили ответа? Какой параметр честнее увеличить: число попыток или паузу?
# 2. **Проверьте `uveren`.** Прогоните все пять случаев через `sprosit_strukturoy` и
#    посчитайте, в скольких случаях `uveren=True` совпало с верным ответом. Можно ли
#    доверять этому полю?
# 3. **Добавьте поле.** Расширьте `OtvetBota` полем `nuzhen_operator: bool` и опишите его
#    в правилах. Что стало с ответами? А если поле описать плохо?
# 4. **Тайм-аут по-настоящему.** Поставьте `timeout=2` у клиента и прогоните журнал случаев.
#    Сколько запросов не уложилось? Как выбрать разумный тайм-аут, не гадая?
#
# **Факультативно.** Хотите увидеть, как шаг 5 делают готовой библиотекой вместо
# ручного цикла — `notebooks-extra/modul2_instructor.py` (не часть программы курса,
# личный ноутбук с библиотекой `instructor`).
#
# ## Что записать в файлы курса
#
# **`cases.jsonl`** — добавьте случай «сервис недоступен»: ожидаемое поведение — понятное
# сообщение, а не Traceback.
#
# **`decisions.md`:**
#
# > **Что сравнивали.** v1 и v2 (тайм-аут, повторы, ответ по схеме) на тех же 5 случаях.
# > **Числа.** Верных ответов: было столько-то, стало столько-то. Падений на ошибках: было
# > столько-то, стало 0.
# > **Что выбрали.** v2: цена та же, устойчивость выше, ответ пригоден для программы.
# > **Чем пожертвовали.** Кода стало больше; появился лишний запрос при сломанном формате.
# > **Когда пересмотреть.** Если поле `uveren` окажется ненадёжным — заменить его
# > проверкой по документам.
#
# **`antipatterns.md`** — «`except Exception: pass` в цикле повторов»: прячет ошибки
# в собственном коде и крутит бесполезные повторы постоянных ошибок.
#
# ## Что унести с собой
#
# * Ошибки делятся на временные и постоянные; повторять имеет смысл только первые.
# * Код 200 не значит годный ответ: бывает обрыв, пустота и не тот формат.
# * Повтор — с лимитом попыток, растущей паузой и разбросом.
# * Схема ответа делает ответ пригодным для программы, но не делает его правдой.
# * Надёжность не лечит незнание: факты нужно давать боту, а не выпрашивать у модели.
