# OpenDoc Model 0.1.0

## Возможности

- Модель документа: Paragraph, Table, Formula, Image, BlockGroup, секции, сноски,
  стили, цвета, свойства, ресурсы, provenance и непрозрачный пакет.
- JSON документа v2 с чтением v1/v2, независимые снимки, unknown-field carriers,
  адресная валидация и DocumentLimits с path/quota/maximum.
- Occurrence walk, атомарная правка, clone, merge/extract с замыканием зависимостей
  и remap известных ссылок.
- Списки, compound items, anchors/internal links, headings, rich Outline labels,
  таблицы и их семантика/границы/отступы.
- FONT/face, наследование стилей, line spacing, tab stops и явный auto.
- PageGeometry, известность PageSettings, ImageSourceRect и BackgroundPaint
  с solid/no-paint/gradient и неизвестными частями.
- IntegrationModel и самостоятельный codec: source mappings, Unicode ranges,
  TextLayout/glyphs, scenes/clip/group scopes, charts, media и diagnostics.
- Структурное сравнение с измеренными областями, явной неизвестностью и
  ограниченным бюджетом сопоставления.

## Установка и границы

Python 3.11+, пакет opendoc-model, импорт opendoc_model. Ядро не имеет обязательных
внешних зависимостей. Optional math использует lxml для поддержанного XML-сравнения
формул. Форматные парсеры, редактор, shaping, rendering и native projection
находятся за пределами библиотеки.

[Руководство](index.md) · [Совместимость](compatibility.md) ·
[API](../reference/api.md) · [Зависимости и лицензии](../development/dependencies.md).
