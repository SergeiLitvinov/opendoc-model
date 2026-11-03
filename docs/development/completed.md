# Возможности OpenDoc Model

Библиотека 0.1.0 предоставляет самостоятельную модель и операции в памяти.
Обязательных runtime dependencies нет; приложение и форматные адаптеры ей не нужны.

| Область | Поддержанный контракт |
| --- | --- |
| Структура | Секции, Paragraph/Table/Formula/Image/BlockGroup, headers/footers, сноски |
| Стили | Наследование, FONT/face, ColorValue/auto, line spacing, tab stops |
| Таблицы | Spans, widths, captions/headers/groups, borders и отступ |
| Ссылки и списки | Anchors, internal links, ListItem/continuations/parents, compound owner |
| Оглавление | Явные IDs/order/targets и отдельный rich label с plain binding |
| Геометрия | Point/Box/страницы, ImageSourceRect и известность PageSettings |
| Фон | Solid Paint, no-paint, gradient stops/alpha и linear/radial/unknown geometry |
| Integration | Диагностика, source map, ranges, TextLayout/glyphs, scenes, charts/media |
| Операции | Occurrence walk, clone, атомарная правка, merge/extract с зависимостями |
| JSON | Документ v2, чтение v1/v2, independent snapshots, atomic write, limits |
| Качество | Структурное сравнение, явная неизвестность и bounded matching |
| Разработка | Строгие типы, installed wheel/sdist checks, CI, Pages и GitHub assets |

Подробные правила: [руководство](../guide/index.md), [API](../reference/api.md)
и [контракт модели](model-contract.md). Форматные парсеры, source bindings,
native projection, редактор и rendering не входят в библиотеку. Структурная
проверка не доказывает visual/native fidelity.
