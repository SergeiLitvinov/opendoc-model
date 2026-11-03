<img src="https://raw.githubusercontent.com/SergeiLitvinov/opendoc-model/main/docs/assets/documentation-logo.svg" width="64" height="64" align="right" alt="OpenDoc Model">

# OpenDoc Model

**Структура документа и операции над ней.**

[![CI](https://github.com/SergeiLitvinov/opendoc-model/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeiLitvinov/opendoc-model/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SergeiLitvinov/opendoc-model)](https://github.com/SergeiLitvinov/opendoc-model/releases)
[![MIT](https://img.shields.io/badge/license-MIT-blue)](docs/LICENSE)

[Документация](https://SergeiLitvinov.github.io/opendoc-model/) · [Руководство](docs/guide/index.md) · [API](docs/reference/api.md) · [Выпуски](https://github.com/SergeiLitvinov/opendoc-model/releases)

Независимая Python-библиотека модели документов и операций в памяти.
Версия: **0.1.0**. Пакет: `opendoc-model`; импорт: `opendoc_model`; Python 3.11+. Обязательных внешних зависимостей нет.

[Размещённые глифы](docs/guide/text-layout.md) связаны с редактируемым
текстом через точные many-to-many диапазоны. Есть атомарная пакетная запись,
явная актуальность привязок и совместимый JSON; shaping и рендеринг остаются
за пределами модели.

[Группы потока](docs/guide/block-groups.md), [rich labels оглавления](docs/guide/outline.md),
[область изображения](docs/guide/image-geometry.md), [известность страницы](docs/guide/page-defaults.md)
и [градиентный фон](docs/guide/backgrounds.md) имеют общие DTO, JSON и лимиты.

Модель, свойства, геометрия, цвета, ресурсы, формулы, обход и изменения, объединение/извлечение с зависимостями, JSON-сериализация, валидация и сравнение структуры работают самостоятельно. Обязательных внешних зависимостей нет. Дополнение `math` предоставляет `lxml` для сравнения поддержанного MathML/Office Math. Без него непроверяемая формула диагностируется, строгий допуск не считается соблюдённым.

```python
from opendoc_model import DocumentModel, Paragraph, Section, TextRun, load_document, save_document

document = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("Мой документ")])])])
save_document(document, "document.json")
restored = load_document("document.json")
assert restored.validate() == []
```

Установка: скачайте wheel из [GitHub Releases](https://github.com/SergeiLitvinov/opendoc-model/releases) и выполните `uv pip install путь/к/opendoc_model-<версия>-py3-none-any.whl`. Сборка из исходников: `uv build --out-dir .opendoc/release-dist`. Для XML-формул добавьте extra: `uv pip install "./opendoc_model-<версия>-py3-none-any.whl[math]"`. Публикация на PyPI пока не выполнялась.

JSON сохраняет идентификатор `opendoc.document` и версию 2, читает версию 1. Версии пакета и JSON независимы. Дополнительные ключи `properties` и `metadata` сохраняются; неизвестные версии и типы блоков отклоняются. Это не обещание чтения произвольной будущей схемы без миграции.

Обработчики прикладных форматов, миграции прежних форматов приложений, шаблоны, задачи, CLI и web принадлежат потребителям. Библиотека работает без редактора; его интерфейс, сеансы и история отмены относятся к отдельному приложению. Чтение JSON сохраняет ресурсы без автоматического преобразования прикладных ролей в пакет OOXML.

Разработка: [контракт участника](docs/development/AGENTS.md), затем `uv sync --all-extras`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`.

[Руководство](docs/guide/index.md) · [API](docs/reference/api.md) · [Навигатор по коду](docs/reference/code.md) · [Возможности](docs/development/completed.md).

[Свойства и стили](docs/guide/styles.md): строгие чтение/запись известных полей и независимый эффективный стиль с разрешением наследования.

[Ресурсы и переносимость](docs/guide/resources.md): явные конфликты ID, поиск использований и одинаковых данных, замена/удаление и встраивание локальных файлов на копии.

[Проверка в памяти](docs/guide/checks.md): структурированные ошибки и сравнение с явными политиками без выходного пути и обращений к внешним файлам.

[Пользовательские расширения](docs/guide/extensions.md): пространства имён, сохраняемые JSON-данные и явно подключаемые валидаторы.

[Расширенная модель](docs/guide/integration.md) : отчёт сохранения, source mapping, диапазоны,
векторная сцена, диаграммы, страницы/медиа, книги и математическое дерево с проверкой ссылок и лимитов.

[Непрозрачные пакеты](docs/guide/packages.md): самостоятельный граф произвольного формата с логическим корнем и связями.

[Зависимости и лицензии](docs/development/dependencies.md): состав ядра, optional math, инструменты разработки,
сборка и компоненты сайта с отдельными лицензионными уведомлениями.

Документация: `uv run python -m tools.docs generate`, затем `uv run python -m tools.docs check`. Локальный сайт: `uv run python -m tools.docs serve`, адрес http://127.0.0.1:8003/. [Как устроена автоматизация](docs/development/documentation.md).

[Стандарты кодирования](docs/development/CODING_STANDARDS.md) проверяются lint и форматированием в CI.

Автоматический выпуск: **Actions → Release → Run workflow**. Выберите `current` для первого выпуска, `patch`, `minor`, `major` или точную версию. Проверки, изменение версии, тег, wheel, исходный архив, SHA-256 и описание выпуска выполняются автоматически. Документация обновляется в Pages после успешных проверок `main`. [Процесс выпуска](docs/guide/release.md).

Вся документация находится в `docs/`; реализованные вехи описаны в [завершённых возможностях](docs/development/completed.md). Временные файлы помещаются в `.opendoc/`. Очистка старых сборок и тестовых окружений: `uv run python -m tools.release clean`.
