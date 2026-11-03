# Зависимости и лицензии

OpenDoc Model распространяется под [MIT](../LICENSE). Copyright:
**2026 Сергей Литвинов (Sergei Litvinov)**. Данные о лицензии включены в wheel
и исходный архив. Сторонние Python-пакеты и native-библиотеки не включаются
в wheel OpenDoc Model. Проверка архитектуры и чистая установка wheel подтверждают
самостоятельность ядра. Уведомления компонентов сайта сохраняют их собственные лицензии.

## Ядро и дополнения

Обязательные внешние runtime-зависимости отсутствуют: `dependencies = []`.
Контракты отступа таблицы и табуляции используют собственный код и стандартную
библиотеку; сторонний код, новые зависимости и лицензии в выпуск 0.11.0 не добавлены.
Поддерживается Python 3.11–3.13; стандартная библиотека поставляется с Python,
а не внутри OpenDoc Model. Сведения об интерпретаторе и его PSF-лицензии доступны в
его собственной поставке.

Дополнения устанавливаются явно:

| Extra / роль | Прямые зависимости | Назначение |
| --- | --- | --- |
| `math` | `lxml>=5.0.0` | Безопасный ограниченный XML-разбор, преобразование и сравнение поддержанного MathML/Office Math |
| `dev` | `mypy>=2.4,<3`, `pytest>=8.0`, `ruff>=0.9.0` | Типы, тесты и стиль при разработке |
| `docs` | `mkdocs>=1.6,<2` | Сборка, поиск и локальный просмотр документации |
| Сборка | `setuptools==84.0.0` | Изолированная сборка wheel и исходного архива |

Версии зависимостей для разработки/CI зафиксированы в `uv.lock`; установка —
`uv sync --all-extras --locked`. Диапазоны extras в опубликованном wheel не
являются обещанием тех же бинарных файлов: конечное окружение фиксирует потребитель.
Wheel OpenDoc Model не включает lxml, его native-библиотеки или инструменты разработки.

## Полный состав Python-пакетов

Используемый XML API описан собственными MIT-аннотациями в
`tools/typing/lxml/`. Они нужны только mypy, не исполняются и не входят в wheel.
Проверка типов не отключена; верные и ошибочные XML-вызовы проверяются тестами.
Замена полного `types-lxml` убрала шесть служебных пакетов и сократила
документированный состав с 35 до 29 без изменения runtime-кода.

Таблица включает прямые и транзитивные зависимости всех extras, а также backend
сборки. `math` относится к optional runtime; `dev`, `docs`, `build` — к поддержке
проекта. Указана основная лицензия пакета. Включённые сторонние компоненты могут
иметь дополнительные уведомления; это не объявление всей поставки пакета MIT.
Их файлы и SHA-256 собраны в [инвентаризации](dependency-inventory.json).

<!-- dependency-table:start -->

| Пакет | Версия в lock/build | Профиль | Основная лицензия |
| --- | --- | --- | --- |
| `ast-serialize` | 0.12.1 | dev | MIT |
| `click` | 8.5.0 | docs | BSD-3-Clause |
| `colorama` | 0.4.6 | dev, docs | BSD-3-Clause |
| `ghp-import` | 2.1.0 | docs | Apache-2.0 |
| `iniconfig` | 2.3.0 | dev | MIT |
| `jinja2` | 3.1.6 | docs | BSD-3-Clause |
| `librt` | 0.16.0 | dev | MIT |
| `lxml` | 6.1.3 | math | BSD-3-Clause |
| `markdown` | 3.11 | docs | BSD-3-Clause |
| `markupsafe` | 3.0.3 | docs | BSD-3-Clause |
| `mergedeep` | 1.3.4 | docs | MIT |
| `mkdocs` | 1.6.1 | docs | BSD-2-Clause |
| `mkdocs-get-deps` | 0.2.2 | docs | MIT |
| `mypy` | 2.4.0 | dev | MIT |
| `mypy-extensions` | 1.1.0 | dev | MIT |
| `packaging` | 26.3 | dev, docs | Apache-2.0 OR BSD-2-Clause |
| `pathspec` | 1.1.1 | dev, docs | MPL-2.0 |
| `platformdirs` | 4.12.2 | docs | MIT |
| `pluggy` | 1.6.0 | dev | MIT |
| `pygments` | 2.21.0 | dev | BSD-2-Clause |
| `pytest` | 9.1.1 | dev | MIT |
| `python-dateutil` | 2.9.0.post0 | docs | Apache-2.0 OR BSD-3-Clause |
| `pyyaml` | 6.0.3 | docs | MIT |
| `pyyaml-env-tag` | 1.1 | docs | MIT |
| `ruff` | 0.16.9 | dev | MIT |
| `setuptools` | 84.0.0 | build | MIT |
| `six` | 1.17.0 | docs | MIT |
| `typing-extensions` | 4.16.0 | dev | PSF-2.0 |
| `watchdog` | 6.0.0 | docs | Apache-2.0 |

<!-- dependency-table:end -->

## Дополнение math и бинарные компоненты

Проверенный lxml 6.1.3 объявляет BSD-3-Clause, но его `LICENSES.txt` отдельно
перечисляет ElementTree/PSF-код и bundled zlib (Zlib), iconv (LGPL-2.1), libxml2,
libxslt и libexslt (MIT с собственными уведомлениями). Конкретная native-поставка
зависит от ОС и способа сборки. OpenDoc Model использует только ограниченный XML API;
ни XML, ни DTD не получают доступа к сети или внешним ресурсам.

В установленном wheel lxml также присутствуют ресурсы isoschematron. Upstream
прямо называет `RNG2Schtrn.xsl` и `XSD2Schtrn.xsl` **unlicensed**. Они не
используются OpenDoc Model и не входят в его wheel. Поэтому аудит подтверждает MIT и
отсутствие чужих бинарных компонентов у самого OpenDoc Model, но не объявляет весь
optional lxml wheel безусловно лицензионно чистым. Если потребитель перепаковывает
lxml или native-библиотеки, он отдельно проверяет их состав и условия, включая
LGPL и эти ресурсы. Исходные сведения: [lxml LICENSES](https://github.com/lxml/lxml/blob/lxml-6.1.3/LICENSES.txt).

## Инструменты и включённые уведомления

`pathspec` использует MPL-2.0 и нужен только инструментам разработки/документации.
`ruff`, `ast-serialize`, `mypy` и `setuptools` включают свои дополнительные
copyright/license notices для заимствованных частей, Rust-компонентов, typeshed
и vendored пакетов. Инвентаризация сохраняет пути и хеши этих файлов.
Они остаются в собственных поставках инструментов и не включаются в wheel OpenDoc Model.

Backend setuptools включает autocommand, backports.tarfile, importlib-metadata,
jaraco.text/context/functools, more-itertools, packaging, platformdirs, tomli,
wheel, zipp и отдельные NOTICE для config/validate-pyproject. Их уведомления
также перечислены в записи setuptools. Ни vendored backend, ни dev-окружение
не переносятся в готовую библиотеку.

В CI используются Python 3.11/3.12/3.13, uv 0.11.13 (MIT OR Apache-2.0), Git
(GPL-2.0) и GitHub Actions checkout/setup-uv/upload-artifact/download-artifact/
configure-pages/upload-pages-artifact/deploy-pages. Actions зафиксированы точными
commit SHA в `.github/workflows/`; они используются как инструменты CI и не
распространяются внутри OpenDoc Model. Их основные лицензии — MIT. ОС runner и
установленные в ней системные пакеты не являются runtime-зависимостями библиотеки.

## Сайт документации

Сайт использует собственные CSS/JS/SVG и поиск MkDocs. Неиспользуемые Bootstrap,
Bootswatch, Font Awesome и webfonts стандартной темы исключены из публикации.
Шрифты интерфейса берутся из системы посетителя; удалённых CDN/fonts нет.

Сохраняются следующие компоненты поиска и их полные уведомления:

| Компонент | Лицензия и исходный текст | Что публикуется |
| --- | --- | --- |
| MkDocs 1.6.1 | [BSD-2-Clause](../licenses/mkdocs-LICENSE.txt) | Код поиска и сборка сайта |
| Lunr.js 2.3.9 | [MIT](../licenses/lunr-LICENSE.txt) | `search/lunr.js` |
| Lunr languages и Russian/Snowball | [MPL-1.1](../licenses/lunr-languages-LICENSE.txt) | `search/lunr.multi.js`, `lunr.stemmer.support.js`, `lunr.ru.js` |
| UMD wrappers | [MIT](../licenses/umd-LICENSE.txt) | Module wrappers в исходниках поиска |

Copyright-заголовки сохранены. Исходный JavaScript публикуется без модификации
и доступен непосредственно в `search/`; лицензии доступны в материалах сайта.
Это лицензии отдельных компонентов документации, а не изменение MIT-лицензии
Python-библиотеки.

`colorama` входит в полный состав для Windows, но не устанавливается на Linux.
Проверка установленного окружения учитывает PEP 508 markers из lockfile;
платформенные различия не сокращают полный документированный состав.

## Повторяемая проверка

`uv run python -m tools.dependencies check` сверяет таблицу и инвентаризацию с
`uv.lock`/build requirement, установленные версии, SPDX metadata и наличие
лицензионных файлов. Проверка включена в CI. Новая зависимость или версия требует
нового просмотра исходных уведомлений, затем явного обновления инвентаризации:

```text
uv sync --all-extras --locked
uv pip install --offline --no-deps --target .opendoc/build-license setuptools==84.0.0
uv run python -m tools.dependencies generate
uv run python -m tools.dependencies check
```

Снимок SHA-256 относится к просмотренным Windows-поставкам; CI на другой платформе
проверяет наличие её собственных уведомлений, не требует байтового равенства
платформенных wheel. Аудит описывает фактический состав выпуска и источники
лицензий; он не заменяет отдельную проверку другой сборки или перепакованной поставки.
