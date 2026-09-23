# Словарик модуля 9

Термины по алфавиту; названия латиницей — в конце.

## CostPerToken

> **CostPerToken** — явно заданная цена входного и выходного токена,
> которую `completion_cost` использует вместо поиска в собственном каталоге.

Из [урока 1](chapter-01.md). Нужен, когда модель — не «настоящая» модель
известного провайдера, а имя на чужом прокси, которого нет в каталоге цен
LiteLLM.

```mermaid
flowchart TD
    A["Имя модели на прокси курса"] --> B{"Есть в каталоге LiteLLM?"}
    B -->|нет| C["Exception: model isn't mapped"]
    B -->|да| D["Цена из каталога"]
    C --> E["Задать CostPerToken явно"]
    E --> F["Стоимость посчитана"]
    D --> F
    style A fill:#2d2d2d,color:#fff
    style B fill:#1a5276,color:#fff
    style C fill:#6e2f1a,color:#fff
    style D fill:#1e8449,color:#fff
    style E fill:#7d6608,color:#fff
    style F fill:#4a235a,color:#fff
```

## Скользящее окно

> **Скользящее окно** — способ считать «сколько было за последнюю минуту»:
> храним времена последних запросов, при каждой проверке выбрасываем те, что
> старше окна, и смотрим, сколько осталось.

Из [урока 2](chapter-02.md). Не нужен отдельный сброс счётчика — старые
запросы сами выпадают из окна со временем.

```mermaid
flowchart TD
    A["Новый запрос: session_id, время"] --> B["Выбросить времена старше окна"]
    B --> C{"В очереди >= лимита?"}
    C -->|да| D["429: превышен лимит"]
    C -->|нет| E["Добавить время, пропустить"]
    style A fill:#2d2d2d,color:#fff
    style B fill:#1a5276,color:#fff
    style C fill:#1a5276,color:#fff
    style D fill:#6e2f1a,color:#fff
    style E fill:#1e8449,color:#fff
```

## Router (LiteLLM)

> **Router** — обёртка LiteLLM, которая при отказе одной модели сама
> переходит на следующую из заданного списка (`fallbacks`).

Из [урока 2](chapter-02.md). Тот же паттерн, что уже реализован вручную на
прокси курса (`ai9-proxy`), только на стороне своего приложения.

```mermaid
flowchart TD
    A["router.completion(model=X)"] --> B{"X ответил?"}
    B -->|да| C["Ответ"]
    B -->|нет| D["Следующая модель из fallbacks"]
    D --> B
    style A fill:#2d2d2d,color:#fff
    style B fill:#1a5276,color:#fff
    style C fill:#1e8449,color:#fff
    style D fill:#7d6608,color:#fff
```
