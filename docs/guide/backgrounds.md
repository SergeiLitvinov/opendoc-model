# Фон и градиентная заливка

**C-BACKGROUND-GRADIENT-01.** Это нейтральные данные модели; парсинг, theme/color resolution,
проекция в исходные форматы, рендеринг и визуальная приёмка остаются у потребителя.

## Роли и правки

`BackgroundPaint(kind, solid=None, gradient=None)` различает:

| Декларация | Смысл |
| --- | --- |
| Нет carrier / getter возвращает None | Фон не объявлен; нет утверждения о наследовании или no-paint |
| kind="unknown" | Фон явно неизвестен |
| kind="none" | Явно не рисовать фон этого scope |
| kind="solid", solid=Paint(...) | Прежний общий Paint и ColorValue, без изменения их API |
| kind="gradient", gradient=GradientPaint(...) | Общий градиент; неизвестные части остаются неизвестными |

Kind должен совпадать с единственным payload. None/unknown не удерживают скрытый
solid/gradient. При правке все объявленные поля авторитетны. Получить getter snapshot,
изменить через dataclasses.replace и явно передать setter — обычный путь сохранения
unknown fields. Новый DTO заменяет data целиком; прежние stops не подмешиваются.
Удаление carrier через None отличается от явного no-paint. Native hints не читаются
и не применяются моделью; потребитель обязан согласовать свои bindings с явной правкой.

`get_section_background` / `set_section_background` работают с Section.properties.
`get_page_background` / `with_page_background` работают с DocumentPage.extra; второй
возвращает независимую страницу, для записи в документ используют прежний set_integration.
Section и page — самостоятельные scopes: автоматического cascade, выбора темы,
источника фона или замены неизвестной геометрии заводскими размерами нет.

## Stops, цвет и неизвестность

GradientPaint.stops — tuple минимум из двух GradientStop либо None (неизвестный набор).
Позиции конечны в [0,1], идут в неубывающем порядке. Совпадающие позиции разрешены,
их порядок сохраняется; сортировки, удаления duplicates или вставки крайних stops нет.
Пустой/одиночный набор отклоняется, а не становится solid или no-paint.

GradientStop.color — прежний ColorValue либо None для неизвестного цвета. Неизвестный
цвет отличается от известного прозрачного цвета. ColorValue.alpha сохраняется;
GradientPaint.opacity отдельно задаёт общую непрозрачность [0,1] либо None. Solid
Paint.opacity по-прежнему имеет прежнее значение по умолчанию 1. Модель не подбирает
цвет по первому stop и не выполняет alpha compositing.

spread — pad/repeat/reflect либо unknown None; interpolation — srgb/linear-srgb либо
unknown None. Они не выбираются автоматически по source markup. CMYK, alpha,
blend_mode и icc_profile сохраняют прежнюю семантику ColorValue: профиль остаётся
его непрозрачной строкой, не новой ссылкой на ресурс. Преобразование цветов не выполняется.

## Геометрия

GradientPaint.linear — LinearGradient(coordinate_space, start, end).
GradientPaint.radial — RadialGradient(coordinate_space, center, radius).
Одновременно задать обе нельзя; обе None означают неизвестную геометрию, включая
непредставимый исходный профиль. Частичный native path не объявляется радиальным
или линейным по догадке. Radial описывает только концентрический круг в объявленном
пространстве, не произвольный focal/path gradient.

coordinate_space задаётся явно: points или relative. Origin — левый верхний угол
локальной области заливки, x направлен вправо, y вниз. Points — пункты. В relative
(0,0) и (1,1) соответствуют углам области; оси масштабируются её шириной и высотой
отдельно. Радиус relative задаётся в этой нормализованной системе: круг может стать
эллипсом в физических координатах прямоугольной области. Никакого дополнительного
сохранения aspect ratio нет. Section относится к его области страницы; DocumentPage —
к исходной неповёрнутой media area. Модель не вычисляет реальную область, clipping,
поворот или mapping из native координат. Неизвестные размеры страницы требуют
решения потребителя, а не заявления об известном визуальном результате.

Координаты конечны, могут выходить за область. Linear endpoints различаются;
radial radius конечный и положительный. Угол, DrawingML ang/scaled/path,
fillToRect/tileRect и другие форматные атрибуты не входят в общий API.

## JSON, обход и лимиты

GradientStop, LinearGradient, RadialGradient, GradientPaint, BackgroundPaint имеют
публичные to_dict/from_dict с limits. Общий carrier: opendoc.background, version=1,
data=<BackgroundPaint>. Unknown fields расширяемых DTO и envelope сохраняются;
известные schema fields не могут быть перекрыты extra. Неподдержанная версия даёт
адресный отказ; opaque collision нельзя перезаписать setter. Mutable JSON независим.

Два полных document JSON-цикла сохраняют роли, stops, alpha, геометрию и unknowns.
Документ остаётся opendoc.document v2, чтение v1/v2; старые конструкторы, solid Paint
и carrier-absent wire/budget не меняются. Старый SDK может переносить carrier как
opaque, что не является поддержкой его семантической правки.

iter_backgrounds даёт отдельные BackgroundLocation(kind, path, background, page_id).
Stops/geometry доступны как typed дочерние значения по их полям и индексам; они
не превращаются в body nodes или VectorPath. Новых resource/anchor ссылок здесь
нет: обход ссылок не угадывает ID из icc_profile либо private extra. Merge/extract
переносят section carrier и page registry по прежним правилам выбора metadata;
новые ресурсы и карты ID не изобретаются.

DocumentLimits учитывают DTO, children и неизвестные JSON данные в codecs,
setter/with_page, полном документе и обходе. Неверные роли, ranges/order, geometry,
версии и циклы дают отказ; исчерпание квоты — ArtifactLimitError. Setter оставляет
прежнюю property mapping при отказе. Нативное качество не устанавливается этими
структурными проверками. Пример: examples/backgrounds.py.
