# Ошибки контрактов

Все gRPC методы требуют API key, отсутствие/неверный — UNAUTHENTICATED. Статусы предметной области заданы enum в proto; время — google.protobuf.Timestamp. Нулевые UNSPECIFIED-статусы не принимаются для записи.

| Условие | gRPC | REST Booking |
|---|---|---|
| Некорректные UUID, IATA, дата, число мест, цена | INVALID_ARGUMENT | 400 VALIDATION_ERROR |
| Рейс не существует | NOT_FOUND | 404 FLIGHT_NOT_FOUND |
| Не хватает мест | RESOURCE_EXHAUSTED | 409 INSUFFICIENT_SEATS |
| Рейс не SCHEDULED, цена изменилась, резерв уже освобождён | FAILED_PRECONDITION | 409 FLIGHT_CONFLICT |
| Другие параметры с прежним booking_id | ALREADY_EXISTS | 409 RESERVATION_CONFLICT |
| Дубликат номера рейса в UTC-день | ALREADY_EXISTS | Операторский RPC |
| Отсутствует/неверен сервисный ключ | UNAUTHENTICATED | 503 UPSTREAM_AUTHENTICATION_FAILED |
| Сервис/БД недоступны | UNAVAILABLE | 503 FLIGHT_UNAVAILABLE |
| Превышен deadline | DEADLINE_EXCEEDED | 503 FLIGHT_TIMEOUT |
| Circuit Breaker открыт | Локальный отказ до сети | 503 CIRCUIT_OPEN |

Дополнительные локальные ошибки: BOOKING_NOT_FOUND (404), INVALID_BOOKING_STATE (409), IDEMPOTENCY_CONFLICT / BOOKING_OPERATION_PENDING / BOOKING_OPERATION_FAILED (409), VALIDATION_ERROR (400), INTERNAL_ERROR (500).

Все REST-ошибки имеют error_code, message, details. Ошибки Pydantic преобразованы из стандартного 422 в 400. Денежные значения в REST и proto — decimal strings, например `"15000.00"`.

## Коды по методам Flight Service

| RPC | Коды ошибок помимо UNAUTHENTICATED / UNAVAILABLE / INTERNAL |
|---|---|
| SearchFlights | INVALID_ARGUMENT — маршрут или дата некорректны |
| GetFlight | INVALID_ARGUMENT — UUID некорректен; NOT_FOUND — рейса нет |
| ReserveSeats | INVALID_ARGUMENT — входные поля; NOT_FOUND — рейса нет; RESOURCE_EXHAUSTED — недостаток мест; FAILED_PRECONDITION — статус, цена или cancellation fence; ALREADY_EXISTS — booking_id использован с другими параметрами |
| ReleaseReservation | INVALID_ARGUMENT — booking_id некорректен; отсутствие резерва не является ошибкой, операция идемпотентна |
| CreateFlight | INVALID_ARGUMENT — поля; ALREADY_EXISTS — номер и UTC-день уже существуют |
| UpdateFlight | INVALID_ARGUMENT — поля; NOT_FOUND — рейса нет; FAILED_PRECONDITION — вместимость меньше резерва; ALREADY_EXISTS — конфликт номера и UTC-дня |
| Health | Проверка подключения к Flight DB; недоступный кеш отражается cache_ok=false |

DEADLINE_EXCEEDED может вернуть gRPC-клиент при превышении срока RPC. Все timestamps передаются через google.protobuf.Timestamp. Номер дня в поиске — YYYY-MM-DD в UTC. seat_count: 1–1000, total_seats: 1–1 000 000; денежные значения положительны, имеют не более двух дробных знаков и выражены в RUB. booking_id и flight_id — UUID.
