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
