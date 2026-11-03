# Аудит OpenDoc Model 0.1.0

## Область и проверки

Аудит охватывает самостоятельные DTO, JSON codecs, валидацию, ссылки, composition,
независимость данных и DocumentLimits. Форматные parsers, source/native bindings,
shaping и rendering не входят в модель. Без измерения сохраняется unknown.

Проверены повреждённые JSON, unknown fields/reserved collisions, ссылки и циклы,
атомарность отказов, два JSON-цикла и точные границы квот. Сохранены независимые
входы document v1/v2. Полный API 0.1.0 зафиксирован в compatibility fixture;
явные корневые реэкспорты включены в __all__ и проверены.

## Внешняя конечная API-приёмка

| Контракт | Подтверждённая область |
| --- | --- |
| C-IMAGE-RECT-01 | Signed/outside viewport, crop migration, extras/JSON, атомарные квоты |
| C-PAGE-DEFAULTS-01 | 10 групп API, source/unknown/computed/explicit, числовая привязка |
| C-BLOCK-GROUP-01 | 8 сценариев, nested scopes, compound owner, anchors, composition, JSON и квоты |
| C-OUTLINE-LABEL-01 | 6 групп, styled/math/empty/absent labels, 10 invalid profiles, правка и зависимости |
| C-BACKGROUND-GRADIENT-01 | 6 групп, coincident stops/alpha/unknown/CMYK, 18 invalid profiles и scopes |

Свидетельства относятся к конечным проверенным API-сценариям. Их исходные пакеты,
hashes и reports сохраняются вне публикуемого дерева. Они не подтверждают
произвольный parser/native exporter, font parsing или visual fidelity.
Собранный wheel 0.1.0 прошёл отдельную изолированную потребительскую приёмку:
все 54 установленных Python-модуля совпали с архивом; py.typed проверен
отдельной installed-типизацией, публичные экспорты и пять
контрактов проверены через JSON/лимиты/атомарные отказы. Дополнительно установленный
потребитель прошёл базовые проверки и самостоятельную PDF-инспекцию без движков.
Это не утверждение о native projection или visual fidelity. SHA256 wheel:
`5ec08c4f4d2f17bb141782b0112dbf10fb7ca3d67f1af4d61e70227c9dccc01a`.

## Качество и зависимости

Локальный полный прогон модели: 2022 passed, 3 platform skips. Ruff, strict mypy,
исполняемые примеры, strict сайт и лицензии прошли. Отдельная установка wheel
без dependencies проверяет публичный API и отсутствие импорта из checkout;
отрицательный typed consumer проверяет ожидаемые ошибки.

Ядро использует стандартную библиотеку. Optional math и dev/docs/build зависимости
перечислены в [инвентаре](dependencies.md); версии сторонних пакетов не менялись.
Лицензия MIT и обязательные notices включаются в wheel/sdist и сайт.

Подготовленные draft-assets проверяются по SHA256SUMS, metadata, archive boundaries
и полному набору package sources; изменение/пропуск модуля отклоняется отдельными
тестами. Принятый wheel публикуется с неизменным SHA256.
