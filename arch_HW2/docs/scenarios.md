# Соответствие критериям и сценарии проверки

Отдельного приложения с E2E-сценариями к условию не предоставлено. Ниже покрыты перечисленные требования, границы и конкурентные операции. Тесты используют реальную PostgreSQL 17.

## Критерии 1–10

| № | Требование | Где реализовано / как проверить |
|---|---|---|
| 1 | Product CRUD, page/size/status/category | OpenAPI paths /products; ProductsController; paginationFilteringAndEmptyPage |
| 2 | Отдельные схемы, required, enum, nullable, decimal/date-time | components.schemas в marketplace.yaml; Python verify_contract.py |
| 3 | Генерация одной командой, без ручных API DTO | Maven generate-sources; generated interfaces в implements; target в .gitignore; чистая Docker-сборка |
| 4 | PostgreSQL, Flyway, status index, timestamps, soft delete | V1__marketplace.sql; SELECT pg_indexes / flyway_schema_history; productCrudAndSoftDelete |
| 5 | Единый формат и каталог ошибок | ErrorResponse / ErrorCode из OpenAPI; ApiExceptionHandler / ErrorWriter; бизнес-тесты и проверка схем ответов |
| 6 | Контрактная валидация до бизнес-операций | Сгенерированные Bean Validation annotations, строгий Jackson; проверки нулевого количества записей после 400 |
| 7 | Заказы, остатки, снимки, скидки, частота, владельцы, состояния | OrderService / PromoService; транзакционные и конкурентные тесты; E2E с SELECT |
| 8 | JSON-логи, UUID, тело, маскирование | RequestLoggingFilter; тест jsonLogsHaveMandatoryFieldsAndMaskSecretsEvenOnForbiddenRequests |
| 9 | Access/refresh JWT, register/login/refresh | AuthController / AuthService / SecurityConfiguration; сроки, неверный тип, expiry, replay и гонка refresh |
| 10 | USER / SELLER / ADMIN и seller_id | Матрица в SecurityConfiguration, проверки объектов в ProductService / OrderService; role/ownership тесты |

## Основные сценарии

| Сценарий | Ожидаемое состояние |
|---|---|
| Создание/чтение/PUT товара | 201/200, UUID и автоматические даты, точная цена |
| DELETE товара | 204, строка существует, status = ARCHIVED; повторный DELETE также 204 |
| Список с default page/size | page = 0, size = 20, content и totalElements |
| Совместные фильтры | AND, category совпадает точно и с учётом регистра |
| Страница за пределами | Пустой content, корректный totalElements |
| Неверные длины, цены, типы, enum, UUID | 400 VALIDATION_ERROR с details.violations; записей нет |
| Description = null и price = 1.2300 | Допускаются; цена хранится как 1.23 |
| U+0000 в name / description / category или фильтре | 400 VALIDATION_ERROR до SQL, вместо внутренней ошибки БД |
| PUT товара: stock + возвращаемый резерв > INTEGER max | 400 VALIDATION_ERROR, старый остаток сохранён; допустимая граница позволяет вернуть резерв без переполнения |
| items пустой / >50 / null-элемент / повтор product_id | 400, остатки не изменены |
| quantity = 0 / 1000, неверный promo pattern | 400 до сервисного метода |
| Покупатель создаёт товар, продавец создаёт заказ | 403 ACCESS_DENIED |
| Продавец меняет чужой товар | 403 ACCESS_DENIED |
| Покупатель читает/меняет/отменяет чужой заказ | 403 ORDER_OWNERSHIP_VIOLATION |
| ADMIN изменяет чужой заказ/товар | Допускается с бизнес-проверками состояния и частоты |
| Несуществующий товар / заказ | PRODUCT_NOT_FOUND / ORDER_NOT_FOUND, 404 |
| Неактивный/архивный товар в заказе | PRODUCT_INACTIVE, 409 |
| Несколько недостаточных остатков | INSUFFICIENT_STOCK, 409; details содержит все проблемные товары |
| Успешный заказ | Остатки уменьшены, цена скопирована в order_items, операция CREATE_ORDER записана |
| Смена цены товара после создания | Исходный снимок и сумма существующего заказа не меняются |
| Повторный POST сразу | ORDER_LIMIT_EXCEEDED, 429; активный заказ проверяется после частоты |
| Повторный POST после N при активном заказе | ORDER_HAS_ACTIVE, 409 |
| Первый PUT сразу после POST | Допускается: CREATE_ORDER и UPDATE_ORDER имеют отдельные интервалы |
| Неудачный PUT после возврата старого резерва | Rollback: прежние позиции, суммы и остатки сохранены; UPDATE_ORDER не записан |
| PUT в PAYMENT_PENDING / PAID / SHIPPED / COMPLETED | INVALID_STATE_TRANSITION, 409 |
| Отмена CREATED / PAYMENT_PENDING | Возвращены остатки и использование промокода, CANCELED |
| Повторная отмена / отмена PAID | 409, повторных возвратов нет |
| Полная цепочка состояний | Только CREATED → PAYMENT_PENDING → PAID → SHIPPED → COMPLETED |
| Недопустимый скачок или отмена через /status | 409; отмена только через /cancel |

## Промокоды и транзакции

| Сценарий | Результат |
|---|---|
| Промокод отсутствует / истёк / не начался / отключён | PROMO_CODE_INVALID, 422; резерв, заказ и операция откатываются |
| current_uses = max_uses | Новое использование запрещено, 422 |
| Создание ниже min_order_amount | PROMO_CODE_MIN_AMOUNT, 422, без изменений |
| PERCENTAGE 10 / 70 / 80 / 100 для суммы 1000 | Итог 900 / 300 / 1000 / 1000 |
| FIXED_AMOUNT больше суммы | discount = сумма, total = 0 |
| Процентное округление на сумме 0.01 | Скидка не превышает 70% после перевода в копейки |
| Изменение своего заказа при занятом последнем использовании | Сохраняет своё использование, не инкрементирует повторно |
| PUT снижает сумму ниже минимальной | Скидка 0, promo_code_id = null, current_uses уменьшается |
| Промокод истёк перед PUT | 422, полный откат обновления |
| Отмена заказа с промокодом | current_uses уменьшается ровно один раз |
| Точное время valid_from / valid_until | Оба конца допустимы; наносекунда снаружи — нет |
| Сумма не помещается в DECIMAL(12,2) | AMOUNT_LIMIT_EXCEEDED, 409, полный откат |

## Конкурентные проверки

| Одновременные запросы | Ожидается |
|---|---|
| Два покупателя, один последний товар | Один 201, второй INSUFFICIENT_STOCK; stock = 0 |
| Два POST одного пользователя | Один 201, второй 429; один заказ и одно резервирование |
| Разные товары, одно последнее использование промокода | Один 201, второй 422; current_uses = 1, резерв проигравшего откатан |
| Два заказа с противоположным порядком product_id | Оба выполняются без deadlock благодаря общему порядку блокировок |
| Два refresh одним токеном | Один 200, второй 401; старый токен отозван |

## Аутентификация и журнал

Проверяются неверный пароль, case-insensitive уникальность email, запрет публичной регистрации ADMIN, отсутствие хеша/пароля в response, истёкший и неверный access, разные типы токенов, истёкший refresh, повторное использование refresh, срок сессии в БД. JSON-логи проверяются на обязательные поля, UUID, время, user_id и маскирование пароля, включая запрос, отклонённый ролью до контроллера.

## Команды

```bash
docker compose --profile test run --rm tests
docker compose up --build -d --wait --wait-timeout 180
python3 scripts/demo.py --evidence evidence/e2e.json
.venv/bin/python scripts/verify_contract.py
```

Последняя команда требует установки requirements-dev.txt в .venv, как описано в README. GitHub Actions выполняет эти проверки и сохраняет отчёты. Тесты очищают только отдельную БД marketplace_test; E2E демонстрация добавляет изолированные demo-объекты в рабочую учебную БД.
