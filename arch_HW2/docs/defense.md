# Защита за 20 минут

## До звонка

Откройте папку `arch_HW2` в редакторе и два терминала в этой же папке. Запустите Docker Desktop. На компьютере нужны Docker Compose и Python 3.10+; Java, Maven, PostgreSQL и psql запускаются в контейнерах.

Один раз заранее проверьте:

```bash
docker compose --profile test run --rm tests
docker compose up --build -d --wait --wait-timeout 180
python3 scripts/demo.py
```

Первое скачивание образов и Maven-зависимостей лучше выполнить до защиты. Для демонстрации запуска достаточно остановить контейнеры через `docker compose down` и снова поднять их при проверяющем. Рабочие данные сохраняются в volume.

## 0–3 минуты: запуск и логи

В первом терминале:

```bash
docker compose up --build -d --wait --wait-timeout 180
docker compose ps
curl -i http://localhost:8081/health
```

Во втором:

```bash
docker compose logs -f --no-color --no-log-prefix api db
```

Пояснение: приложение сначала проверяет/применяет миграции Flyway; API и PostgreSQL должны быть healthy. `/health` выполняет также SELECT 1. По X-Request-Id видно соответствующую JSON-строку запроса в логах.

## 3–8 минут: цепочка HTTP → PostgreSQL

```bash
python3 scripts/demo.py
```

Скрипт показывает реальную цепочку: регистрация продавца/покупателей → JWT → товар → промокод → заказ → резерв → изменение цены → проверка снимка → обновление позиций → снятие промокода ниже минимума → отмена → мягкое удаление → модель состояний.

Не пропускайте напечатанные SELECT. На экране должны быть видны:

- products.stock после резерва и после отмены;
- orders.total_amount / discount_amount / status;
- order_items.price_at_order;
- promo_codes.current_uses;
- user_operations с разными типами операций.

Для дополнительного ручного SQL откройте интерактивный клиент:

```bash
docker compose exec db psql -U marketplace -d marketplace
```

В нём:

```sql
SELECT id, name, price, stock, status FROM products ORDER BY created_at DESC LIMIT 10;
SELECT id, user_id, status, total_amount, discount_amount FROM orders ORDER BY created_at DESC LIMIT 10;
SELECT order_id, product_id, quantity, price_at_order FROM order_items;
SELECT code, current_uses, max_uses FROM promo_codes;
SELECT user_id, operation_type, created_at FROM user_operations ORDER BY created_at DESC LIMIT 10;
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'products';
SELECT version, description, success FROM flyway_schema_history;
```

Выход из psql: `\q`.

## 8–12 минут: другие входные данные

Откройте <http://localhost:8081/swagger-ui/index.html>. Swagger UI читает исходный контракт `/openapi/marketplace.yaml`.

1. В `/auth/login` войдите локальным ADMIN: admin@example.test / Admin-demo-123!.
2. Скопируйте access_token в Authorize. Refresh для этого не подходит.
3. Через `/products` создайте новый товар. Сохраните его настоящий UUID.
4. Для действий покупателя зарегистрируйте USER через `/auth/register`, выполните login и смените токен в Authorize. Для роли SELLER — аналогично.

Примеры альтернатив:

| Действие | Результат |
|---|---|
| Создать товар с price = 0, stock = -1, пустым name | 400 VALIDATION_ERROR и конкретные поля |
| Создать товар с ролью USER | 403 ACCESS_DENIED |
| Список с size = 0 или неизвестным status | 400 VALIDATION_ERROR |
| Купить больше остатка | 409 INSUFFICIENT_STOCK, остаток не изменяется |
| Сразу повторить успешное создание заказа | 429 ORDER_LIMIT_EXCEEDED — лимит проверяется раньше активного заказа |
| После истечения N создать второй активный заказ | 409 ORDER_HAS_ACTIVE |
| Прочитать/изменить чужой заказ как USER | 403 ORDER_OWNERSHIP_VIOLATION |
| Неверный или истёкший промокод | 422 PROMO_CODE_INVALID; резерв откатывается |
| Сумма создания ниже min_order_amount | 422 PROMO_CODE_MIN_AMOUNT |
| Обновление существующего заказа ниже min_order_amount | Успех, скидка снимается, счётчик уменьшается |
| Повторно отменить заказ | 409 INVALID_STATE_TRANSITION, повторного возврата нет |
| Попробовать CREATED → PAID через ADMIN /status | 409 INVALID_STATE_TRANSITION |
| Использовать refresh как access | 401 TOKEN_INVALID |
| Повторить уже использованный refresh | 401 REFRESH_TOKEN_INVALID |

В живой демонстрации N = 1 минута. Не нужно менять SQL-историю, чтобы обойти лимит: можно дождаться N или зарегистрировать другого покупателя. Интеграционные тесты моделируют прошедший интервал в отдельной тестовой БД.

## 12–17 минут: что открыть в коде

| Файл | Что объяснить |
|---|---|
| `src/main/resources/openapi/marketplace.yaml` | Обязательные поля, ограничения, отдельные create/update/response, роли, ошибки |
| `pom.xml` | Генератор запускается на generate-sources до компиляции |
| `target/generated-sources/openapi/.../ProductsApi.java` | Сгенерированные сигнатуры и @Valid; файл получается командой generate |
| `.../api/ProductsController.java` | implements ProductsApi, принимает сгенерированный DTO, делегирует сервису |
| `.../service/OrderService.java` | @Transactional, порядок проверок, создание/обновление/отмена, rate limit, FSM |
| `.../persistence/MarketplaceRepository.java` | Настоящие SQL, параметризация, FOR UPDATE, порядок блокировок |
| `.../service/PromoService.java` | Срок, счётчик, денежная формула, 70%, округление |
| `.../security/SecurityConfiguration.java` | Разделение access/refresh, проверка JWT, матрица ролей |
| `.../service/AuthService.java` | Хеш пароля, выпуск пары токенов, атомарная ротация refresh |
| `.../error/ApiExceptionHandler.java` | Ошибки валидации, HTTP-коды, единый generated ErrorResponse |
| `.../logging/RequestLoggingFilter.java` | UUID до security, маскирование, длительность, user_id |
| `src/main/resources/db/migration/V1__marketplace.sql` | Таблицы, FK, ENUM, индекс status, partial unique index, timestamp trigger |

Префикс `...` в таблице означает `src/main/java/ru/marketplace`.

Создание заказа можно объяснить так: «Я блокирую строку владельца, проверяю частоту и активный заказ. Затем блокирую товары в общем порядке UUID, проверяю весь каталог и все остатки. Резерв, строки заказа, снимки цен, использование промокода и запись операции находятся в одной транзакции. Любая бизнес-ошибка — RuntimeException, поэтому Spring откатывает изменения».

При обновлении объясните, почему возврат прежнего резерва безопасен: он находится в той же транзакции, что новый резерв. Если новые позиции не подходят, PostgreSQL откатывает и возврат, поэтому старый заказ остаётся прежним.

## 17–20 минут: базовая теория

**Почему здесь монолит, хотя в первом задании были микросервисы?** У этого задания есть требование одной транзакции между stock и orders. Модули работают в одном приложении и одной БД. С приватными БД отдельных сервисов пришлось бы применять saga, что меняет требуемую гарантию.

**Что такое contract-first?** Сначала задаётся OpenAPI. Генератор создаёт API-интерфейсы и DTO, контроллер реализует этот интерфейс. Изменять generated-файлы вручную нельзя: следующая сборка их перезапишет. DTO не лежат в Git, но попадают в собранный JAR.

**Чем интерфейс отличается от реализации?** Интерфейс задаёт методы и типы. Реализующий его контроллер обязан предоставить эти методы; несовместимое изменение контракта обнаруживается при компиляции.

**Зачем @Transactional?** Spring связывает JDBC-вызовы публичного сервисного метода с одной транзакцией. При успехе — commit, при выброшенном RuntimeException — rollback. Самостоятельно открывать разные соединения в этих методах не нужно.

**Как решается гонка за последний товар?** SELECT FOR UPDATE блокирует строку. Второй запрос ждёт, а после снятия блокировки видит уже изменённый остаток. CHECK(stock >= 0) — дополнительная защита БД. Сначала блокируются все участвующие товары в одинаковом порядке, чтобы уменьшить вероятность deadlock.

**Почему блокируется пользователь?** Чтобы даже два первых одновременных заказа, когда строки user_operations ещё нет, не прошли проверку одновременно. FOR NO KEY UPDATE сериализует операции владельца и совместим с FK KEY SHARE. Partial unique index дополнительно запрещает два активных заказа.

**Почему BigDecimal?** Денежные десятичные значения нельзя надёжно считать двоичным double. В Java сумма и скидка вычисляются BigDecimal, в БД сохраняются DECIMAL(12,2). Правило округления задаётся явно.

**Что такое JWT?** Подписанный набор claims, включая sub, role и exp. Подпись проверяет подлинность и целостность, а не скрывает payload. Нельзя доверять role без проверки подписи, срока и типа токена. Access и refresh имеют разное назначение.

**Почему пароль — хеш, а не шифрование?** Пароль не требуется восстанавливать. PBKDF2 с солью позволяет проверить совпадение и усложняет перебор. Пароль не попадает ни в response DTO, ни в журнал.

**Зачем БД для refresh, если он тоже JWT?** Она позволяет отозвать конкретный refresh и сделать его одноразовым. Одной проверки подписи для этого недостаточно. В БД хранится хеш токена, а запись блокируется при ротации.

**401 и 403?** 401 — отсутствует или не подходит аутентификация. 403 — токен принят, но нет необходимой роли или права на объект.

**Что делает Flyway?** Применяет версионированные миграции и хранит историю/контрольные суммы. SQL-схема не создаётся вручную через psql. Применённую миграцию не переписывают; новое изменение оформляют следующей версией.

**Что подтверждают тесты и зелёный CI?** Только настроенные проверки конкретного коммита. Здесь проверяются HTTP-контракт, настоящая PostgreSQL, бизнес-ошибки, транзакции, гонки и Docker E2E. Это не означает готовности сервиса к произвольной production-нагрузке.
