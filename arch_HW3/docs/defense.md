# Защита за 20 минут: Flight Booking

## Перед звонком

Запустить Docker Desktop. Открыть `arch_HW3` в редакторе и два терминала в этой папке. Заранее выполнить `sh scripts/test.sh`: скачивание образов и зависимостей не должно занимать время защиты. Затем проверить обычный запуск `docker compose up --build -d --wait --wait-timeout 240` и `python3 scripts/demo.py`. Остановка с сохранением данных — `docker compose down`.

## 0–3 минуты: архитектура и запуск

> Два микросервиса имеют отдельные базы. Клиент обращается к REST Booking. Booking вызывает Flight по gRPC. Flight владеет рейсами и местами, Booking — пассажирскими данными, суммой и статусом бронирования. Redis с Sentinel — кеш Flight. Взаимодействие сервисов защищено API key в metadata.

Показать архитектуру README и ER в docs/er.md. В первом терминале:

```bash
docker compose up --build
```

Во втором:

```bash
docker compose ps
curl -i http://localhost:8082/health
curl 'http://localhost:8082/flights?origin=SVO&destination=LED'
```

Показать Alembic в логах каждого сервиса. Объяснить, почему здесь две БД и нет SQL JOIN между сервисами.

## 3–7 минут: E2E и SELECT

```bash
python3 scripts/demo.py
```

Показать не только PASS, но и SELECT внутри вывода:

- Новый рейс: 10 мест по 7500.
- Бронирование 2 мест: available_seats=8; reservation ACTIVE; booking CONFIRMED, total_price=15000.
- Цена рейса изменяется на 9000: стоимость уже созданного бронирования остаётся 15000.
- Повтор Idempotency-Key: тот же booking_id, одна резервация.
- Недостаток мест: ошибка, существующие остатки не меняются, лишнего booking нет.
- Отмена: reservation RELEASED, booking CANCELLED, available_seats=10.

Для дополнительного SQL:

```bash
docker compose exec flight-db psql -U flight -d flight
```

```sql
SELECT id,flight_number,available_seats,total_seats,price,status FROM flights;
SELECT booking_id,flight_id,seat_count,status FROM seat_reservations;
SELECT version_num FROM alembic_version;
```

Затем `\q` и другая БД:

```bash
docker compose exec booking-db psql -U booking -d booking
```

```sql
SELECT id,user_id,flight_id,seat_count,total_price,status FROM bookings;
SELECT booking_id,state,last_error FROM booking_operations;
SELECT version_num FROM alembic_version;
```

Точечные запросы делайте с UUID, который только что вернул скрипт/API.

## 7–10 минут: ручной Swagger и gRPC

Открыть http://localhost:8082/docs. Для этого проекта логин не нужен: API key передаётся между сервисами, а не через пользователя.

1. GET /flights: Try it out; origin=SVO, destination=LED, date оставить пустым; Execute. Выбрать настоящий UUID рейса SCHEDULED.
2. POST /bookings: Try it out; заменить flight_id на выбранный, user_id — произвольный корректный UUID. Email — `ivan@example.com`, seat_count=2. Не используйте домен `.test`: стандартный email-валидатор считает его специальным.
3. Скопировать id бронирования из Server response 201. GET /bookings/{booking_id} — вставить UUID в отдельное поле, Execute.
4. POST /bookings/{booking_id}/cancel — тот же UUID, Execute; повтор — 409.
5. Альтернатива: seat_count=0 → 400; больше available_seats → 409; несуществующий flight UUID → 404. Проверить SELECT, что мест не стало меньше после ошибки.

Шаблон POST:

```json
{
  "user_id":"00000000-0000-0000-0000-000000000101",
  "flight_id":"00000000-0000-0000-0000-000000000001",
  "passenger_name":"Ivan Petrov",
  "passenger_email":"ivan@example.com",
  "seat_count":2
}
```

Прямой аутентифицированный gRPC:

```bash
echo '{"flight_id":"00000000-0000-0000-0000-000000000001"}' | docker compose exec -T flight python scripts/grpc_cli.py GetFlight
```

Без ключа — UNAUTHENTICATED:

```bash
echo '{"flight_id":"00000000-0000-0000-0000-000000000001"}' | docker compose exec -T flight python scripts/grpc_cli.py GetFlight --no-auth
```

## 10–13 минут: Redis, retry, Circuit Breaker

Повторить GET одного рейса дважды. Показать hit/miss и TTL:

```bash
docker compose logs --no-log-prefix flight
docker compose exec flight python scripts/cache_status.py
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name flights
```

Остановить Flight:

```bash
docker compose stop flight
```

Повторить GET /flights/{id} несколько раз. В логах Booking видны попытки 1/2/3 и CLOSED → OPEN. После порога следующий запрос немедленно даст 503 CIRCUIT_OPEN. Показать:

```bash
curl http://localhost:8082/diagnostics
docker compose logs --tail=50 --no-log-prefix booking
```

Восстановить:

```bash
docker compose start flight
```

После 10 секунд допустить пробный GET: HALF_OPEN → CLOSED и 200. Первый запрос слишком рано всё ещё получит 503 — это ожидаемо.

Для отдельной проверки Sentinel можно остановить **текущий** master, который показал SENTINEL get-master-addr-by-name. Например, если это redis-master:

```bash
docker compose stop redis-master
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name flights
```

Подождать promotion, повторить GET и cache_status.py. Затем вернуть остановленный узел через `docker compose start redis-master`. Не останавливайте узел по имени вслепую после предыдущего failover: текущим master уже может быть redis-replica-1/2.

Полная автоматическая демонстрация отказов входит в `sh scripts/test.sh` и выполняется в отдельном тестовом проекте. На защите выбирайте ручные сценарии по времени и вопросам проверяющего.

## 13–17 минут: код

| Открыть | Объяснить |
|---|---|
| contracts/flights/v1/flight.proto | Бизнес-RPC, UUID, Timestamp, enum, decimal-строка и error codes |
| scripts/generate.py, Dockerfile | Настоящий protoc; generated не хранится в Git; сборка повторяема |
| services/flight/server.py | Server interceptor проверяет API key для всех RPC; трансляция ошибок |
| services/flight/service.py, ReserveSeats | SELECT FOR UPDATE, проверка состояния/мест, уменьшение счётчика и INSERT одной транзакцией |
| ReleaseReservation | Идемпотентный возврат; cancellation fence против позднего ReserveSeats |
| services/booking/service.py, create | Durable intent → GetFlight → ReserveSeats → snapshot → локальная запись; компенсация |
| recover_once | Незавершённые операции восстанавливаются после процесса/сети; advisory lock защищает активный запрос |
| services/booking/interceptors.py | Retry отдельно от бизнес-логики, breaker отдельно от retry, один HALF_OPEN probe |
| services/flight/cache.py | Cache-Aside, TTL, Sentinel-клиент, fallback и epoch |
| services/*/migrations/versions/0001_schema.py | Раздельные схемы, 3NF, реальные CHECK/UNIQUE/FK |

## 17–20 минут: теория, вопрос — ответ

**Почему gRPC?** Строгий protobuf-контракт, generated stub/servicer, типизированные сообщения и стандартные статусы. REST оставлен для клиента. gRPC — сетевой RPC, а не общая SQL-транзакция.

**Зачем Timestamp и enum?** Timestamp передаёт абсолютное время в стандартизованном формате; enum ограничивает набор статусов. Нулевой UNSPECIFIED предназначен для отсутствующего значения и отклоняется для создания рейса.

**Что гарантирует SELECT FOR UPDATE?** Конкурентный запрос ждёт строку рейса и после первого commit видит новый остаток. Счётчик и резервация изменяются одной транзакцией. CHECK дополнительно запрещает отрицательные места.

**Что если ReserveSeats выполнился, а ответ потерялся?** Retry повторяет тот же booking_id. UNIQUE и проверка входов возвращают исходную резервацию, места второй раз не уменьшаются.

**Что если Booking упал после успешного резерва?** До RPC сохранён durable intent. После перезапуска worker видит незавершённый CREATING и освобождает резерв. Если Flight временно недоступен, операция остаётся для повторной компенсации. Пока связи нет, мгновенную глобальную атомарность двух БД обещать нельзя.

**Что если отмена пришла раньше запоздавшего резерва?** Release сохраняет cancellation fence даже для отсутствующего booking_id. Поздний Reserve видит его и не занимает места.

**Какие ошибки повторяются?** Только UNAVAILABLE и DEADLINE_EXCEEDED, максимум 3 попытки суммарно. Паузы 100/200 ms. INVALID_ARGUMENT, NOT_FOUND и RESOURCE_EXHAUSTED не повторяются.

**Что делает Circuit Breaker?** Считает логические вызовы после retries. CLOSED пропускает, OPEN сразу отклоняет, HALF_OPEN допускает один пробный вызов после таймера. Это предотвращает постоянную нагрузку на недоступный сервис и долгие ожидания клиента.

**Чем retry отличается от breaker?** Retry повторяет отдельный временно неуспешный вызов. Breaker временно прекращает вызовы после серии сбоев.

**Чем Sentinel отличается от Cluster?** Sentinel выбирает master среди реплик и сообщает клиенту адрес. Cluster также распределяет ключи по hash slots. Здесь маленький кеш, поэтому выбран Sentinel с репликами и quorum=2.

**Что такое Cache-Aside?** Сначала читаем кеш; на miss получаем данные из БД и кладём с TTL. После изменений инвалидируем. БД остаётся источником истины.

**Зачем epoch, если есть DEL и TTL?** Между чтением и заполнением кеша может пройти мутация, а при асинхронном failover удаление может потеряться. Версия в PostgreSQL не позволяет использовать старую запись. Цена — лёгкий SELECT даже при cache hit; это явно описанный trade-off.

**Что будет без Redis?** Flight использует PostgreSQL. Отсутствие кеша не должно запрещать бронирование. Без Flight DB кеш не подменяет источник истины.

**Почему схема в 3NF?** Атрибуты зависят от ключей; airline_name вынесен в airlines; дата вылета не дублируется отдельным полем; индексы вычисляют UTC-день. Цена резервации и сумма бронирования — исторические факты, не текущие справочные значения.

**Где аутентификация пользователя?** В задании требуется межсервисная аутентификация. Реализован API key в gRPC metadata, user_id приходит в REST-запросе. Это не JWT-авторизация клиентов из предыдущей домашки.

**Что такое миграция?** Версионированное изменение схемы. Alembic применяет её до запуска сервиса и хранит revision в alembic_version. Два сервиса мигрируют свои БД независимо.

**Что реально проверили?** Unit и интеграционные проверки на настоящих контейнерах, SELECT двух БД, потерю ответа, локальный сбой, recovery intent, гонки, cache stale entry, настоящую остановку Flight и Redis master. Зелёный тест подтверждает эти сценарии, а не отсутствие любых возможных проблем.
