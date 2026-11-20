# Keitaro Desk

Обёртка над Keitaro: создание кампании с двумя потоками и редактор привязок офферов с черновиками, архивом, закреплением долей и историей публикаций

FastAPI · SQLAlchemy 2 · PostgreSQL · Alembic · React · TypeScript · Docker Compose

## Запуск

Нужны Docker Desktop с запущенным Engine и API-ключ Keitaro с правами на кампании и потоки

```powershell
Copy-Item .env.example .env
# Укажите KEITARO_BASE_URL и KEITARO_API_KEY в .env
docker compose up --build -d
```

На Linux/macOS вместо `Copy-Item` используйте `cp .env.example .env`

Открыть [приложение](http://localhost:8000), [Swagger](http://localhost:8000/docs), [liveness](http://localhost:8000/live), [readiness](http://localhost:8000/ready)

Миграции выполняет отдельный контейнер до старта приложения; PostgreSQL сохраняет данные в именованном volume

```sh
docker compose logs --tail 50 app migrate
docker compose run --rm migrate alembic upgrade head
docker compose run --rm migrate alembic current
docker compose down
```

`down` сохраняет данные БД; не используйте `down -v`, если хотите сохранить операции и архив

## Демо без доступа к Keitaro

Остановите обычный вариант, если он запущен: оба используют локальный порт 8000

```sh
docker compose down
docker compose -f compose.yaml -f compose.demo.yaml up --build -d
```

Это отдельный локальный симулятор HTTP API с собственным volume БД, без запросов к реальному трекеру; для редактора используйте кампанию `101`, офферы `1111`, `3749`, `3717`, `1112`, `5001`; домен, группа и источник имеют ID `1`

При перезапуске симулятор сбрасывает свою память, а локальная история редактора остаётся в PostgreSQL; при конфликте отмените черновик или явно примите текущее состояние Keitaro

Чтобы переключиться на настоящий трекер, выполните `docker compose -f compose.yaml -f compose.demo.yaml down`, затем `docker compose up --build -d` без demo override

## Два экрана

**Создать кампанию:** введите название, ISO-код страны и ID существующего оффера; выберите домен, группу и источник из API Keitaro; `DEFAULT_DOMAIN_ID`, `DEFAULT_GROUP_ID`, `DEFAULT_TRAFFIC_SOURCE_ID` необязательны и предзаполняют форму

Кампания создаётся выключенной; первый поток отправляет указанную страну на Google, второй — остальных на оффер; после чтения и проверки обоих потоков кампания включается

**Редактор:** укажите ID кампании и нажмите Fetch streams; Add, Remove, Bring back и закрепления меняют серверный черновик; Push публикует один поток, Cancel восстанавливает последний подтверждённый снимок

Удаление касается только привязки; сам оффер не удаляется; известные привязки, удалённые через админку Keitaro, после Fetch попадают в локальный архив

Удалённые привязки показываются с 0%; закреплённые доли сохраняются; остаток делится поровну между активными незакреплёнными офферами; остаточные целые проценты получает конец стабильного списка, например `25 + 37 + 38 = 100`

Fetch сохраняет прочитанные значения без автоматической записи: если в Keitaro осталось `25 + 25`, экран покажет 50% с пояснением; перерасчёт произойдёт при следующем редактировании

Потоки без офферов доступны для просмотра; удаление последнего активного оффера запрещено; выключенные привязки сохраняются выключенными и не участвуют в распределении

![Редактор с закреплением и архивом](docs/editor.jpg)

## Сбои и согласованность

- Создание и публикация принимают `Idempotency-Key`; тот же ключ и запрос возвращают ту же операцию, другой запрос с этим ключом даёт 409
- Намерение шага сохраняется до HTTP-записи, подтверждение — после неё; транзакции БД короткие, сетевых вызовов внутри транзакций записи нет
- После таймаута или 5xx записи результат считается неизвестным; создание сверяется по alias кампании и маркерам потоков, слепые повторы POST запрещены
- Кнопка «Продолжить / сверить» в истории продолжает подтверждённые шаги и проверяет неизвестные; если результат POST не найден, нужен осмотр трекера, автоматический повтор остаётся заблокирован
- Публикация сравнивает актуальный снимок с базовым до PUT и повторно читает поток после него; запрос меняет только `offers`
- Неизвестная публикация блокирует новые правки до сверки; «Принять Keitaro» явно отбрасывает черновик и принимает удалённое состояние, без отката уже выполненной записи
- Версия черновика защищает от потери правок между вкладками; блокировка ресурса в БД сериализует изменения кампании, после аварии процесса освобождается по сроку 10 минут
- Keitaro не предоставляет здесь условную запись CAS; гонка с изменениями через его админку полностью не исключается

Подробнее: [архитектура и принятые допущения](docs/architecture.md), [проверка реального API](docs/live-verification.md), [план](plan.md)

## Разработка без Docker

Python 3.12+ и Node.js 22+; PostgreSQL рекомендуется, SQLite доступен для быстрого локального запуска

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -c requirements.lock -e ".[dev]"
# Для SQLite задайте DATABASE_URL=sqlite:///./keitaro.db в .env
.\.venv\Scripts\alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Для frontend с hot reload запустите `npm run dev` в `frontend/`, оставив backend на порту 8000; Vite проксирует `/api` на backend

Для полностью локального демо без Docker отдельно запустите `python -m uvicorn tools.demo_keitaro:app --port 9001` и задайте `KEITARO_BASE_URL=http://127.0.0.1:9001`, `KEITARO_API_KEY=demo-local-only`

## Тесты и миграции

```powershell
.\.venv\Scripts\python -m pytest --cov=app --cov-report=term-missing
.\.venv\Scripts\python -m ruff check app tests tools migrations
.\.venv\Scripts\python -m ruff format --check app tests tools migrations
cd frontend
npm test
npm run format:check
npm run build
cd ..
.\.venv\Scripts\alembic check
.\.venv\Scripts\python -m tools.check_migrations
```

Unit-тесты проверяют расчёт долей и HTTP-клиент; интеграционные тесты проходят через FastAPI, SQLAlchemy и HTTP MockTransport с отдельной БД на тест; реальные HTTP-запросы в Keitaro не отправляются

По умолчанию тесты используют SQLite; для PostgreSQL задайте `TEST_DATABASE_URL=postgresql+psycopg://keitaro:keitaro@127.0.0.1:5432/keitaro` — каждый тест создаст собственную схему и удалит только её; пользователю БД нужны права CREATE SCHEMA

CI запускает интеграционные тесты на PostgreSQL 17, frontend-тесты, сборку, линтер, миграции вверх/вниз и сборку Docker-образа

Новая миграция: `alembic revision --autogenerate -m description`, проверка файла, затем `alembic upgrade head`; для отката используйте `alembic downgrade -1`

## Конфигурация и безопасность

API-ключ читается только сервером из `.env`; `.env` исключён из Git и Docker-контекста; в образ передаются переменные окружения, во frontend ключа нет

HTTP-ошибки не возвращают сырое тело Keitaro и не логируют ключ; ошибки API содержат `code`, `message` и `request_id`; история сохраняет изменения привязок и статусы шагов

Compose публикует порты только на `127.0.0.1`; для внешнего доступа настройте HTTPS и аутентификацию reverse proxy либо `APP_ACCESS_TOKEN` — это отдельный токен обёртки, который интерфейс хранит только в sessionStorage вкладки

Readiness проверяет доступность таблиц БД и наличие серверного ключа, без запроса к Keitaro на каждом probe; ошибку самого трекера интерфейс показывает при обращении к API

## Источники поведения

[ТЗ и видео редактора](https://www.youtube.com/watch?v=jNloscEWCjA) · [Admin API](https://admin-api.docs.keitaro.io/) · [Потоки Keitaro](https://docs.keitaro.io/en/campaigns-and-streams/streams.html)

## Отправка на GitHub

Создайте пустой репозиторий без README, подключите его URL и отправьте текущую ветку

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/keitaro-desk.git
git push -u origin HEAD
```

`.env`, локальные БД, окружение Python и node_modules не входят в репозиторий
