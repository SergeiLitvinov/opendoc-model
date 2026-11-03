# Известность геометрии страницы

**C-PAGE-DEFAULTS-01.** Модель хранит общие состояния и числовую привязку;
парсинг исходных форматов, выбор defaults среды и нативные измерения остаются
за потребителем. Ни Word/OOXML, ни A4/Letter по расширению файла не выбираются.

## Число и известность — отдельные данные

Прежний `Section.page: PageSettings` сохраняет шесть обязательных Length:
width/height и margin_top/right/bottom/left. Они остаются рабочими числами для
совместимости. При неполном исходном документе потребитель сам выбирает допустимые
placeholders, но не объявляет их доказательством геометрии источника.

`PageSettingsState` содержит шесть независимых `PageSettingValue`. По умолчанию
все поля нового DTO — unknown, без числовых значений. Неизвестность включается
явным вызовом setter, а не сравнением с заводскими числами PageSettings.

| state | value | Смысл |
| --- | --- | --- |
| `source` | Length | Производитель явно сообщает известное исходное значение |
| `unknown` | None | Источник не объявил значение либо оно неизвестно |
| `computed` | Length | Оценка с обязательным непустым `basis` |
| `explicit` | Length | Пользователь явно принял или переопределил настройку |

Известный нулевой margin — `source/explicit` с `Length(0)`, а не unknown.
Все Length выражены в пунктах; bool, строки, NaN/Infinity, overflow и отрицательные
значения отклоняются. Width/height положительны. Актуальные известные margins
не могут поглотить известную ширину/высоту; рабочий PageSettings также проходит
прежнюю проверку всех шести чисел.

`basis` — непрозрачное основание/пояснение производителя, не исполняемая формула
и не native XML. У computed оно обязательно; у остальных состояний опционально.
Состояния являются явными утверждениями вызывающего кода, а не результатом
самостоятельного измерения библиотекой.

Отдельное `freshness` принимает `current` или `stale`. Оно описывает актуальность
числовой привязки. Даже `computed/current` остаётся оценкой, а не известной
исходной геометрией. Изменение внешней среды, данных или политики вычисления
должен обработать потребитель: basis не разрешается и его зависимости не
вычисляются автоматически.

## Публичный API

| API | Поведение |
| --- | --- |
| `PageSettingsState.to_dict(*, limits=None)` / `.from_dict(data, *, limits=None)` | Официальный общий typed codec, независимые Length и unknown fields |
| `get_page_settings_state(section, *, limits=None)` | Независимые эффективные состояния; прямые числовые правки сообщаются как stale |
| `set_page_settings_state(section, state, *, limits=None)` | Атомарное объявление состояний и применение только current известных значений |
| `accept_page_settings(section, fields=None, *, limits=None)` | Явное принятие текущих рабочих чисел выбранных полей как explicit/current |
| `invalidate_page_settings(section, fields=None, *, limits=None)` | Сохранение stale с прежним состоянием, значением и basis, без изменения чисел |
| `set_page_settings_state(section, None, *, limits=None)` | Возврат к legacy только после разрешения всех unknown/computed/stale полей |

Имена fields — `PageSettingName`: width, height и четыре margin. None выбирает
все поля. Строка вместо iterable, повтор или неизвестное имя отклоняются;
итерация ограничена бюджетом. Пустой набор проверяет привязку без изменения.
Accept/invalidate требуют явно включённого tracking.

Setter не подставляет числа в unknown. Для unknown/stale остаются текущие рабочие
PageSettings; устаревшее значение DTO не перезаписывает их. Для current
source/computed/explicit переданная Length применяется явно. Это также позволяет
явно переопределить число через `dataclasses.replace` DTO.

```python
from opendoc_model import (
    PageSettingsState,
    Section,
    accept_page_settings,
    get_page_settings_state,
    set_page_settings_state,
)

section = Section()  # Прежние рабочие числа; их происхождение пока не описано.
set_page_settings_state(section, PageSettingsState())  # Все шесть unknown.
old_number = section.page.width.pt
accept_page_settings(section, ("width",))
assert section.page.width.pt == old_number
assert get_page_settings_state(section).width.state == "explicit"
assert get_page_settings_state(section).height.value is None
```

Присваивание такого же числа напрямую не выражает принятия: unknown остаётся
unknown. При другом числе getter помечает соответствующее поле stale, не
изменяя документ. JSON и полная валидация отклоняют незаписанное устаревание
до явного accept/replace/invalidate. Если напрямую изменены несколько полей,
пакет accept/invalidate должен включать их все, иначе отказ атомарен.

Для удаления оценки замените поле на `PageSettingValue('unknown')`: прежнее
рабочее число останется placeholder, но известное значение исчезнет. Invalidate
вместо этого сохраняет старую оценку и basis как stale. Stale переживает JSON
и не становится current само по себе, даже если рабочее число вернулось назад.

Удаление всего carrier при unresolved полях запрещено. Сначала явно примите
либо переопределите их; source/explicit current можно перенести обратно в legacy.
Это явная потеря tracking, не доказательство исходного происхождения чисел.

## JSON, совместимость и бюджеты

Carrier — `Section.properties['opendoc.page-settings-state']` версии 1.
В нём `state` содержит DTO, а `projection` — полный снимок шести рабочих Length
на момент записи. Projection не является значением unknown и не подтверждает
source geometry. Отсутствующие projection поля не заполняются defaults:
повреждённый снимок отклоняется. Отсутствующие поля state становятся unknown.

Прежние Section/PageSettings и JSON без carrier сохраняют своё поведение;
getter возвращает None, не вставляет metadata и не переоценивает legacy Model.
Отсутствие tracking само по себе не подтверждает source geometry. JSON документа
остаётся 2 с чтением 1/2. Старый читатель способен переносить carrier как
неизвестное property, но не распознаёт его состояния и ограничения.

Неизвестные JSON-поля DTO, каждого значения, envelope и projection сохраняются
при правке. Переданные extra имеют приоритет над прежними; возвращённые и
сохранённые контейнеры независимы. Неизвестная версия известного format даёт
адресный отказ; opaque значение не интерпретируется и не перезаписывается.

DocumentLimits передаётся через все шаги codec/валидации/commit. Unknown fields
тоже расходуют nodes/depth/bytes. Превышение остаётся ArtifactLimitError с
path/quota/maximum; ошибки не оставляют частичных изменений. Файлы, шаблоны,
ресурсы среды и внешние основания не открываются.

Clone/merge/extract сохраняют состояния и снимок без принятия предположений.
Этот контракт относится к шести полям Section.page; он не заменяет DocumentPage/
PageGeometry и не вычисляет пагинацию. Инспекция рабочих чисел не превращается
в подтверждение исходных размеров или нативной полноты переноса.

Исполняемый пример: [page_defaults.py](../../examples/page_defaults.py).
