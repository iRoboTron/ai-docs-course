# %% [markdown]
# # Дубль модуля 2 через библиотеку: Instructor
#
# **Личная лаба, не часть программы курса.** В шаге 5 модуля 2 мы сами написали цикл
# «просим JSON → `pydantic.ValidationError` → один повтор с подсказкой» (`sprosit_strukturoy`).
# Посмотрим, что из этого кода делает за нас готовая библиотека `instructor` — и чего
# не делает.
#
# | Шаг | Что делаем |
# |---|---|
# | 1 | Подключаемся (как в модуле 2) |
# | 2 | Та же схема ответа `OtvetBota` |
# | 3 | Instructor вместо ручного цикла: `sprosit_strukturoy` → `client.chat.completions.create` |
# | 4 | Ломаем формат нарочно — смотрим, как Instructor повторяет сам |
# | 5 | Чего Instructor не решает: `uveren` остаётся мнением модели |
#
# **Запросов к модели:** около 15, плюс лишние при намеренной поломке формата.

# %%
!pip -q install openai pydantic instructor

# %% [markdown]
# ## Шаг 1. Подключаемся `[как в модуле 2]`

# %%
import getpass
import os

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

import instructor


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
        print(f"Подключились. Модель: {MODEL}")
    except Exception as oshibka:
        print(f"Не подошло: {type(oshibka).__name__} — {str(oshibka)[:120]}")
        API_KEY = None

PRAVILA = (
    "Ты помощник сервисного центра «Полярис»: ремонт бытовой техники. "
    "Отвечай вежливо и коротко, максимум два предложения, на русском языке."
)

SLUCHAI = [
    {"id": "subbota", "vopros": "Во сколько вы закрываетесь в субботу?", "zhdem": "17:00"},
    {"id": "garantiya", "vopros": "Какая у вас гарантия на ремонт?", "zhdem": "12 месяц"},
    {"id": "podshipniki", "vopros": "Сколько стоит замена подшипников в стиральной машине?", "zhdem": "4900"},
    {"id": "samokaty", "vopros": "Вы чините электросамокаты?", "zhdem": "не знаю"},
    {"id": "diagnostika", "vopros": "Диагностика платная?", "zhdem": "1200"},
]

# %% [markdown]
# ## Шаг 2. Та же схема ответа `[как в модуле 2, шаг 5]`
#
# Модель `OtvetBota` — буква в букву та же, что мы писали руками. Меняется только то,
# кто её проверяет и повторяет запрос при провале.

# %%
class OtvetBota(BaseModel):
    otvet: str = Field(description="ответ гостю, одно-два предложения")
    uveren: bool = Field(description="true, если ответ основан на точных данных")
    chego_ne_hvataet: str | None = Field(default=None, description="каких данных не хватило")

# %% [markdown]
# ## Шаг 3. Instructor вместо ручного цикла `[пишем вместе]`
#
# В модуле 2 `sprosit_strukturoy` — это ~20 строк: собрать сообщения, попросить JSON,
# поймать `ValidationError`, вручную дописать повтор с подсказкой. Instructor оборачивает
# тот же клиент и делает это за один вызов: отдай `response_model`, получи готовый объект
# или исключение после исчерпанных попыток.
#
# `mode=instructor.Mode.JSON` — тот же режим `response_format={"type": "json_object"}`,
# которым мы уже пользовались в модуле 2. Режим `TOOLS` (по умолчанию у Instructor)
# нашему прокси не всегда подходит — не все модели одинаково хорошо вызывают функции.

# %%
ic = instructor.from_openai(client, mode=instructor.Mode.JSON)


def sprosit_instructor(vopros, podrobno=True):
    return ic.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=200,
        max_retries=2,
        response_model=OtvetBota,
        messages=[{"role": "system", "content": PRAVILA}, {"role": "user", "content": vopros}],
    )


for vopros in ("Во сколько вы закрываетесь в субботу?", "Вы чините электросамокаты?"):
    rezultat = sprosit_instructor(vopros)
    print(f"❓ {vopros}")
    print(f"   otvet: {rezultat.otvet}")
    print(f"   uveren: {rezultat.uveren}, чего не хватает: {rezultat.chego_ne_hvataet}\n")

# %% [markdown]
# **Что посмотреть в выводе:** результат — тот же объект `OtvetBota`, что и в модуле 2.
# Разница не в том, что получилось, а в том, сколько кода понадобилось, чтобы это
# получить: Instructor сам строит инструкцию по схеме, разбирает JSON, проверяет
# `pydantic`-модель и при ошибке формата сам формирует повтор с текстом ошибки.

# %% [markdown]
# ## Шаг 4. Ломаем формат нарочно `[пишем вместе]`
#
# В модуле 2 мы наблюдали повтор только когда модель сама путала формат. Заставим её
# промахнуться специально — сильно урежем `max_tokens`, чтобы JSON обрывался, — и
# посмотрим, как Instructor обрабатывает это сам.

# %%
try:
    rezultat = ic.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=8,  # заведомо мало: JSON не влезет целиком
        max_retries=2,
        response_model=OtvetBota,
        messages=[{"role": "system", "content": PRAVILA},
                  {"role": "user", "content": "Расскажите подробно про все виды ремонта."}],
    )
    print("Всё же получилось:", rezultat)
except Exception as oshibka:
    print(f"Не получилось после всех попыток: {type(oshibka).__name__}")
    print(f"   {str(oshibka)[:200]}")

# %% [markdown]
# **Что посмотреть в выводе:** Instructor исчерпал `max_retries` и поднял исключение —
# ровно то же решение, что мы сами закодировали в `sprosit_strukturoy` (`raise` на второй
# неудачной попытке). Разница только в том, что лимит попыток и текст подсказки для
# повтора Instructor формирует сам, а не мы вручную.

# %% [markdown]
# ## Шаг 5. Чего Instructor не решает `[пишем вместе]`
#
# Прогоним журнал случаев `SLUCHAI` и посмотрим на поле `uveren` — ту самую ловушку
# из модуля 2, шаг 7: модель говорит «уверена» не потому, что права, а потому что так
# звучит увереннее.

# %%
print(f"{'случай':<14} {'ждём':<10} {'uveren':<8} ответ")
for sluchay in SLUCHAI:
    rezultat = sprosit_instructor(sluchay["vopros"], podrobno=False)
    verno = sluchay["zhdem"].lower() in rezultat.otvet.lower()
    print(f"{sluchay['id']:<14} {'✅' if verno else '❌':<10} "
          f"{str(rezultat.uveren):<8} {rezultat.otvet[:60]}")

# %% [markdown]
# **Что посмотреть в выводе:** как и в модуле 2, `uveren` почти всегда `True`, даже там,
# где ответ неверный — потому что мы не дали боту фактов о «Полярисе», только правила
# вежливости. Instructor решает **формат** ответа (валидный объект вместо текста), но
# не решает **правду**: за неё по-прежнему отвечают данные, которые видит модель. Это
# работа RAG из модулей 3-4, а не структурированного вывода.
#
# > Instructor убирает ~20 строк ручного цикла повтора, но не убирает необходимость
# > самим проверять, чему верить в ответе, — тот же принцип, что и с фреймворками
# > оценки из модуля 6: готовый инструмент меняет **как** мы получаем результат,
# > а не то, **что** мы обязаны проверить сами.

# %% [markdown]
# ## Попробуй сам
#
# 1. Добавь в `OtvetBota` поле `nuzhen_operator: bool` с описанием и прогони журнал
#    случаев. Как быстро Instructor подстроился под новое поле — пришлось ли что-то
#    менять в вызове?
# 2. Сравни число запросов к модели у `sprosit_strukturoy` из модуля 2 и у
#    `sprosit_instructor` здесь на одних и тех же пяти случаях `SLUCHAI` — считай
#    вручную по счётчику или через `client.chat.completions.create` с оберткой,
#    печатающей каждый вызов.
# 3. Поставь `mode=instructor.Mode.TOOLS` вместо `Mode.JSON` — что изменится
#    в поведении на нашем прокси? Работает ли вообще?
