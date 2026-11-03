# Оглавление и закладки

`Outline`, `OutlineEntry` и `OutlineTarget` представляют независимую
иерархию навигации. Оглавление не строится автоматически из оформления или
заголовков. Библиотека хранит декларации, проверяет ссылки и сохраняет их
при JSON и композиции; она не отображает меню и не выполняет переходы.

## Записи и назначения

`OutlineEntry(id, title, order, parent_id=None, target=None, provenance=None)`
имеет устойчивый ID внутри оглавления. `parent_id=None` означает корневую запись.
Order — неотрицательное целое, уникальное среди записей с одинаковым parent;
значения могут иметь пропуски. Tuple хранит записи, но его положение не заменяет
order. Для отображения вызывающий группирует записи по parent и сортирует по order.
Title — обычный текст, включая пустой; форматированное содержимое этим полем не
подменяется. `Provenance` хранит происхождение записи.

`OutlineTarget(kind, target_id=None, uri=None, point=None, zoom=None)` различает:

| Kind | Назначение |
| --- | --- |
| `anchor` | Существующий `Anchor.id` структурного узла; только target_id |
| `page` | Существующий `DocumentPage.id`; target_id и необязательные point/zoom |
| `external` | Непустая инертная uri; без target_id, point или zoom |

`target=None` означает неизвестное/отсутствующее назначение. Неизвестное назначение
не заменяется внешней ссылкой или первой страницей. Внешняя uri хранится как текст;
её доступность не проверяется, никаких сетевых запросов или действий не выполняется.
Path обхода и исходный номер страницы не используются вместо ID.

Page point — `Point2D` в исходной системе страницы, в пунктах, до crop и поворота.
Оси направлены вправо и вниз. Отсутствие point означает неизвестную позицию;
точки вне области страницы сохраняются без clipping. Zoom — положительная конечная
доля (1.25 означает 125 процентов), а не процент; отсутствие означает неизвестное.
Для явной [геометрии страницы](page-geometry.md) вызывающий может применить
`page_point_to_display`. Трансформация автоматически не меняет назначение.

## API и проверки

`get_outline(document, limits=None)` возвращает независимую запись либо `None`,
проверяя синтаксис и иерархию. `set_outline(document, outline, limits=None)`
проверяет весь документ и атомарно заменяет оглавление; `None` удаляет известную
декларацию, сохраняя остальной integration-конверт. Для нового оглавления
конверт создаётся при необходимости. Назначения page требуют заранее заданных pages.

ID уникальны, parent существует, циклы и повтор order среди соседей отклоняются.
Якорные и страничные назначения проверяются при set, JSON, `document.validate()`
и `check_document`. Код ошибок — `outline.invalid`; расположение указывает запись
или поле. Структурная операция, удаляющая внутреннее назначение, откатывается.
Число и объём данных ограничены `DocumentLimits`; глубина иерархии дополнительно
ограничена max_depth независимо от плоского хранения записей. Превышение даёт
`ArtifactLimitError`, без частичного результата.

## JSON и композиция

Собственная tagged-схема v1 хранится в `IntegrationModel.extra` под
`opendoc.outline` с format, version и entries. Integration v1 и JSON документа
v1/v2 не изменены. Reader без поддержки дополнения сохраняет неизвестное поле,
но не проверяет его отношения. Непомеченное содержимое занятого ключа остаётся
непрозрачным; setter не перезаписывает и не удаляет его. Неизвестная tagged-версия
отклоняется. Неизвестные поля Outline/Entry/Target сохраняются в их extra.
Явный null в занятом ключе также непрозрачен: setter отказывает (API 0.1.0).
Setter объединяет прежние неизвестные поля верхней записи; для правок вложенных
записей используйте прочитанные записи и `dataclasses.replace`.

Merge переназначает anchor-назначения по существующим картам документа.
`metadata_conflicts="keep_first"/"keep_last"` выбирает integration-конверт целиком:
оглавление, pages и остальные записи берутся из одного входа. Собственные ID
оглавления и pages сохраняются, два набора записей автоматически не объединяются.
`remap_outline(outline, entry_ids=None, anchor_ids=None, page_ids=None, limits=None)`
даёт независимую запись с явным переназначением ID и родителей. Ключи, отсутствующие
в карте, сохраняются. После ремапа проверяются уникальность, иерархия и бюджеты;
существование назначений проверит setter в целевом документе. URI и private extra
не переписываются.

Extract сохраняет всё оглавление и замыкает его anchor-зависимости; это может
сохранить целые дополнительные секции. Entries и parents не отсекаются молча.
Pages остаются в сохраняемом конверте. [Исполняемый пример](../../examples/outline.py)
показывает JSON, объединение и извлечение. Дополнение не вводит измерение
сохранности внешнего оглавления, парсер документов или управление закладками UI.

## Отдельная форматированная подпись: C-OUTLINE-LABEL-01

**C-OUTLINE-LABEL-01.**
`OutlineEntry.label` — keyword-only optional `OutlineLabel(title, content)`.
Content — tuple существующих TextRun и Formula, без скрытого Paragraph или
изменения body Heading. Label не задаёт назначение в исходном формате: потребитель
выбирает, какая запись применяется к оглавлению или running mark. Несколько entries
могут иметь один target anchor; SDK не выбирает первый или последний label.

`label=None` сохраняет прежний plain title и не добавляет поля в JSON или расходов
на отсутствующее поле в model budget. `OutlineLabel("", ())` — явно пустая rich
подпись; entry.title также должен быть пустым. Это отличается от отсутствия label.

`OutlineLabel.title` — явно заданное вызывающим кодом plain-представление и привязка
к `OutlineEntry.title`. Они обязаны совпадать. Модель не парсит формулу для получения
строки. Изменение title при сохранённом несовпадающем label отклоняется: нужно явно
заменить оба или снять label через `replace(entry, title="New", label=None)`.
Правка content при прежнем plain title разрешена, включая смену форматирования.
Удалённый label не восстанавливается из старых данных. `set_outline` фиксирует
полный независимый снимок атомарно; прямые правки результата getter остаются локальными.

Inline Formula допускается только с display=False и непустым явным fallback_text.
Image/Paragraph/Table и другие inline-типы здесь отклоняются. Существующие
TextRun styles, FONT/face, provenance, внешние ссылки, internal links на body anchors
и visual surrogate resource refs сохраняются. Объявления новых anchors и footnote
references в label отклоняются; идентичность label не подменяет идентичность body.

`iter_outline_inlines(document, limits=...)` даёт отдельные detached
`OutlineInlineLocation(entry_id, index, node, path)`. Это адрес в текущем outline,
его нужно обновлять после перестановки/правки. `walk_model`, body text metrics и
обычные structural node edits остаются обходом тела. Для правки label используют
get_outline → replace → set_outline. `iter_font_references` включает прямые FONT
ссылки label, также как detached snapshots. Наследование run.style можно разрешить
обычным resolve_style; шрифты не ищутся и не загружаются автоматически.
Инспекция сохраняет rich outline отдельно в metadata, не добавляя label в body text.

Общий outline envelope v1 расширен optional полем label; версия документа остаётся
2 с чтением 1/2. Label.content использует типизированную схему core dataclasses
(text/style/font_size.pt либо value/format/display/fallback_text), а не wire body
block с discriminator type. Это явно разные позиции JSON. Unknown поля Outline,
Entry, Label и открытых properties сохраняются. Неизвестные поля закрытых core
TextRun/Formula/TextStyle записей отклоняются адресно, не отбрасываются. Mutable
данные входного DTO, JSON, getter и восстановленной модели независимы.

remap_outline принимает также optional resource_ids/style_ids, переименовывая
FONT, style, surrogate и internal-link ссылки label. Merge делает это по обычным
картам, extract замыкает anchor/style/resource зависимости label. Политика выбора
целого outline envelope при слиянии не меняется. Opaque extras не интерпретируются.
Старый SDK может переносить неизвестное optional поле как extra; это не поддержка
семантической правки label старым SDK, stale binding новый SDK не принимает молча.

DocumentLimits охватывают label/children, unknown JSON, ссылки и embedded ресурсы.
Точные границы model/setter и полного JSON transport могут различаться; общий
бюджет передаётся, отказ не оставляет частичных metadata. Форматные парсеры,
escaping, source bindings, rendering и native acceptance остаются вне библиотеки.
Исполняемый пример: `examples/outline_labels.py`.
