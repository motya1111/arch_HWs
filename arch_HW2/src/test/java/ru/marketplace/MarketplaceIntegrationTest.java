package ru.marketplace;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.databind.*;
import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Stream;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.*;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.test.web.servlet.*;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import ru.marketplace.generated.model.Role;
import ru.marketplace.persistence.MarketplaceRepository;
import ru.marketplace.security.SecurityConfiguration;

@SpringBootTest
@AutoConfigureMockMvc
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class MarketplaceIntegrationTest {
  @Test
  void validationDetailsNameTheFieldAndExpectedType() throws Exception {
    var invalidPrice = productBody("Wrong type", "10.00", 1, "ACTIVE");
    var response = error(call("POST", "/products", seller, invalidPrice), 400, "VALIDATION_ERROR");
    assertThat(response.path("details").path("violations").get(0).path("field").asText())
        .isEqualTo("price");
    assertThat(response.path("details").path("violations").get(0).path("message").asText())
        .contains("number");
    var unknown = productBody("Unknown", 10, 1, "ACTIVE");
    unknown.put("unknown_field", "not allowed");
    var unknownResponse =
        error(call("POST", "/products", seller, unknown), 400, "VALIDATION_ERROR");
    assertThat(unknownResponse.path("details").path("violations").get(0).path("field").asText())
        .isEqualTo("unknown_field");
    assertThat(unknownResponse.path("details").path("violations").get(0).path("message").asText())
        .contains("not allowed");
    assertThat(count("products")).isZero();
  }

  @Autowired MockMvc mvc;
  @Autowired ObjectMapper json;
  @Autowired JdbcTemplate jdbc;
  @Autowired MarketplaceRepository repository;
  @Autowired PasswordEncoder passwords;
  @Autowired JwtEncoder encoder;
  UUID userId, otherId, sellerId, otherSellerId, adminId;
  String user, other, seller, otherSeller, admin, hash;
  ListAppender<ILoggingEvent> logs;
  private static final String PASSWORD = "Testing-secret-123!";

  @BeforeAll
  void prepareHashAndGuardDatabase() {
    assertThat(jdbc.queryForObject("SELECT current_database()", String.class))
        .isEqualTo("marketplace_test");
    hash = passwords.encode(PASSWORD);
  }

  @BeforeEach
  void fixtures() {
    jdbc.execute(
        "TRUNCATE refresh_tokens,user_operations,order_items,orders,promo_codes,products,users"
            + " CASCADE");
    userId = account("user@example.test", Role.USER);
    otherId = account("other@example.test", Role.USER);
    sellerId = account("seller@example.test", Role.SELLER);
    otherSellerId = account("seller2@example.test", Role.SELLER);
    adminId = account("admin@example.test", Role.ADMIN);
    user = token(userId, "USER", "access", Instant.now().plusSeconds(900));
    other = token(otherId, "USER", "access", Instant.now().plusSeconds(900));
    seller = token(sellerId, "SELLER", "access", Instant.now().plusSeconds(900));
    otherSeller = token(otherSellerId, "SELLER", "access", Instant.now().plusSeconds(900));
    admin = token(adminId, "ADMIN", "access", Instant.now().plusSeconds(900));
    logs = new ListAppender<>();
    logs.start();
    ((Logger) LoggerFactory.getLogger("marketplace.requests")).addAppender(logs);
  }

  @AfterEach
  void detachLogs() {
    ((Logger) LoggerFactory.getLogger("marketplace.requests")).detachAppender(logs);
    logs.stop();
  }

  UUID account(String email, Role role) {
    return repository.insertAccount(email, hash, role).id();
  }

  String token(UUID id, String role, String kind, Instant expiry) {
    var claims =
        JwtClaimsSet.builder()
            .issuer(SecurityConfiguration.ISSUER)
            .subject(id.toString())
            .id(UUID.randomUUID().toString())
            .issuedAt(Instant.now().minusSeconds(120))
            .expiresAt(expiry)
            .claim("role", role)
            .claim("token_type", kind)
            .build();
    return encoder
        .encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims))
        .getTokenValue();
  }

  MvcResult call(String method, String path, String token, Object body) throws Exception {
    MockHttpServletRequestBuilder request =
        switch (method) {
          case "POST" -> post(path);
          case "PUT" -> put(path);
          case "DELETE" -> delete(path);
          case "PATCH" -> patch(path);
          default -> get(path);
        };
    if (token != null) request.header("Authorization", "Bearer " + token);
    if (body != null) {
      request.contentType(MediaType.APPLICATION_JSON);
      if (body instanceof Raw raw) request.content(raw.value());
      else request.content(json.writeValueAsBytes(body));
    }
    return mvc.perform(request).andReturn();
  }

  record Raw(String value) {}

  JsonNode expect(MvcResult result, int status) throws Exception {
    assertThat(result.getResponse().getStatus())
        .as(result.getResponse().getContentAsString())
        .isEqualTo(status);
    assertThatCode(() -> UUID.fromString(result.getResponse().getHeader("X-Request-Id")))
        .doesNotThrowAnyException();
    if (status == 204) {
      assertThat(result.getResponse().getContentAsString()).isEmpty();
      return json.nullNode();
    }
    assertThat(result.getResponse().getContentType()).startsWith("application/json");
    return json.readTree(result.getResponse().getContentAsString());
  }

  JsonNode error(MvcResult result, int status, String code) throws Exception {
    var body = expect(result, status);
    assertThat(body.path("error_code").asText()).isEqualTo(code);
    assertThat(body.path("message").asText()).isNotBlank();
    return body;
  }

  Map<String, Object> productBody(String name, Object price, int stock, String status) {
    var body = new LinkedHashMap<String, Object>();
    body.put("name", name);
    body.put("price", price);
    body.put("stock", stock);
    body.put("category", "Books");
    body.put("status", status);
    return body;
  }

  UUID product(String name, String price, int stock) throws Exception {
    return UUID.fromString(
        expect(
                call(
                    "POST",
                    "/products",
                    seller,
                    productBody(name, new BigDecimal(price), stock, "ACTIVE")),
                201)
            .path("id")
            .asText());
  }

  Map<String, Object> item(UUID id, int quantity) {
    return Map.of("product_id", id, "quantity", quantity);
  }

  Map<String, Object> orderBody(UUID id, int quantity) {
    return Map.of("items", List.of(item(id, quantity)));
  }

  JsonNode order(UUID id, int quantity, String token) throws Exception {
    return expect(call("POST", "/orders", token, orderBody(id, quantity)), 201);
  }

  int stock(UUID id) {
    return jdbc.queryForObject("SELECT stock FROM products WHERE id=?", Integer.class, id);
  }

  int uses(UUID id) {
    return jdbc.queryForObject(
        "SELECT current_uses FROM promo_codes WHERE id=?", Integer.class, id);
  }

  long count(String table) {
    return jdbc.queryForObject("SELECT count(*) FROM " + table, Long.class);
  }

  void age(String operation) {
    jdbc.update(
        "UPDATE user_operations SET created_at=clock_timestamp()-interval '2 minutes' WHERE"
            + " operation_type=CAST(? AS operation_type)",
        operation);
  }

  void amount(JsonNode node, String field, String expected) {
    assertThat(node.path(field).decimalValue()).isEqualByComparingTo(expected);
  }

  JsonNode promo(
      String code,
      String type,
      String value,
      String min,
      int max,
      Instant from,
      Instant until,
      boolean active)
      throws Exception {
    return expect(
        call(
            "POST",
            "/promo-codes",
            seller,
            Map.of(
                "code",
                code,
                "discount_type",
                type,
                "discount_value",
                new BigDecimal(value),
                "min_order_amount",
                new BigDecimal(min),
                "max_uses",
                max,
                "valid_from",
                from.toString(),
                "valid_until",
                until.toString(),
                "active",
                active)),
        201);
  }

  JsonNode promo(String code, String type, String value, String min, int max) throws Exception {
    return promo(
        code,
        type,
        value,
        min,
        max,
        Instant.now().minusSeconds(60),
        Instant.now().plusSeconds(3600),
        true);
  }

  JsonNode orderWithPromo(UUID product, int quantity, String code, String token) throws Exception {
    return expect(
        call(
            "POST",
            "/orders",
            token,
            Map.of("items", List.of(item(product, quantity)), "promo_code", code)),
        201);
  }

  @Test
  void productCrudAndSoftDelete() throws Exception {
    UUID id = product("Book", "12.34", 10);
    var initial = expect(call("GET", "/products/" + id, user, null), 200);
    amount(initial, "price", "12.34");
    assertThat(initial.path("seller_id").asText()).isEqualTo(sellerId.toString());
    var changed =
        expect(
            call(
                "PUT",
                "/products/" + id,
                seller,
                productBody("New book", new BigDecimal("20.00"), 4, "INACTIVE")),
            200);
    assertThat(changed.path("created_at")).isEqualTo(initial.path("created_at"));
    assertThat(changed.path("updated_at")).isNotEqualTo(initial.path("updated_at"));
    expect(call("DELETE", "/products/" + id, seller, null), 204);
    expect(call("DELETE", "/products/" + id, seller, null), 204);
    assertThat(count("products")).isEqualTo(1);
    assertThat(expect(call("GET", "/products/" + id, user, null), 200).path("status").asText())
        .isEqualTo("ARCHIVED");
    error(call("POST", "/orders", user, orderBody(id, 1)), 409, "PRODUCT_INACTIVE");
  }

  @Test
  void paginationFilteringAndEmptyPage() throws Exception {
    product("First", "1.00", 1);
    UUID second = product("Second", "2.00", 1);
    expect(call("DELETE", "/products/" + second, seller, null), 204);
    var defaults = expect(call("GET", "/products", user, null), 200);
    assertThat(defaults.path("size").asInt()).isEqualTo(20);
    assertThat(defaults.path("totalElements").asInt()).isEqualTo(2);
    var page = expect(call("GET", "/products?page=1&size=1&category=Books", user, null), 200);
    assertThat(page.path("content").get(0).path("id").asText()).isEqualTo(second.toString());
    assertThat(page.path("page").asInt()).isEqualTo(1);
    assertThat(
            expect(call("GET", "/products?status=ACTIVE&category=Books", user, null), 200)
                .path("totalElements")
                .asInt())
        .isEqualTo(1);
    assertThat(
            expect(call("GET", "/products?category=books", user, null), 200)
                .path("totalElements")
                .asInt())
        .isZero();
    var beyond = expect(call("GET", "/products?page=99&size=1", user, null), 200);
    assertThat(beyond.path("content").size()).isZero();
    assertThat(beyond.path("totalElements").asInt()).isEqualTo(2);
  }

  @ParameterizedTest
  @ValueSource(strings = {"name", "description", "category"})
  void nullCharactersAreRejectedBeforePersistence(String field) throws Exception {
    var body = productBody("Book", 10, 1, "ACTIVE");
    body.put(field, "before\u0000after");
    var response = error(call("POST", "/products", seller, body), 400, "VALIDATION_ERROR");
    assertThat(response.path("details").path("violations").toString()).contains(field);
    assertThat(count("products")).isZero();
  }

  @Test
  void nullCharacterInCategoryFilterIsAValidationError() throws Exception {
    error(
        mvc.perform(
                get("/products")
                    .param("category", "before\u0000after")
                    .header("Authorization", "Bearer " + user))
            .andReturn(),
        400,
        "VALIDATION_ERROR");
  }

  @ParameterizedTest
  @ValueSource(strings = {"CREATED", "PAYMENT_PENDING"})
  void stockReplacementLeavesRoomForReturningReservations(String status) throws Exception {
    UUID productId = product("Capacity", "1", 10);
    String orderId = order(productId, 2, user).path("id").asText();
    if (status.equals("PAYMENT_PENDING"))
      expect(call("PATCH", "/orders/" + orderId + "/status", admin, Map.of("status", status)), 200);
    var excessive = productBody("Capacity", 1, Integer.MAX_VALUE - 1, "ACTIVE");
    var response =
        error(call("PUT", "/products/" + productId, seller, excessive), 400, "VALIDATION_ERROR");
    assertThat(response.path("details").path("violations").toString()).contains("stock");
    assertThat(stock(productId)).isEqualTo(8);
    expect(
        call(
            "PUT",
            "/products/" + productId,
            seller,
            productBody("Capacity", 1, Integer.MAX_VALUE - 2, "ACTIVE")),
        200);
    expect(call("POST", "/orders/" + orderId + "/cancel", user, null), 200);
    assertThat(stock(productId)).isEqualTo(Integer.MAX_VALUE);
  }

  static Stream<Arguments> invalidProductFields() {
    return Stream.of(
        Arguments.of("name", ""),
        Arguments.of("name", "  "),
        Arguments.of("name", "x".repeat(256)),
        Arguments.of("name", 123),
        Arguments.of("description", "x".repeat(4001)),
        Arguments.of("price", 0),
        Arguments.of("price", -1),
        Arguments.of("price", new BigDecimal("0.001")),
        Arguments.of("price", new BigDecimal("1.001")),
        Arguments.of("price", "10.00"),
        Arguments.of("stock", -1),
        Arguments.of("stock", 1.5),
        Arguments.of("stock", "1"),
        Arguments.of("category", ""),
        Arguments.of("category", "x".repeat(101)),
        Arguments.of("status", "BOGUS"),
        Arguments.of("status", null),
        Arguments.of("id", UUID.randomUUID().toString()));
  }

  @ParameterizedTest
  @MethodSource("invalidProductFields")
  void productValidationBeforePersistence(String field, Object value) throws Exception {
    var body = productBody("Book", new BigDecimal("1.00"), 1, "ACTIVE");
    body.put(field, value);
    var response = error(call("POST", "/products", seller, body), 400, "VALIDATION_ERROR");
    assertThat(response.path("details").path("violations").isArray()).isTrue();
    assertThat(count("products")).isZero();
  }

  @ParameterizedTest
  @ValueSource(
      strings = {
        "page=-1",
        "page=1000001",
        "page=x",
        "size=0",
        "size=101",
        "status=BOGUS",
        "page=",
        "size=",
        "status=",
        "category="
      })
  void invalidQueryParameters(String query) throws Exception {
    error(call("GET", "/products?" + query, user, null), 400, "VALIDATION_ERROR");
  }

  @ParameterizedTest
  @ValueSource(strings = {"{", "[]", "null", "{\"name\":true}"})
  void invalidJson(String body) throws Exception {
    error(call("POST", "/products", seller, new Raw(body)), 400, "VALIDATION_ERROR");
  }

  @Test
  void nullableDescriptionAndDecimalTrailingZeros() throws Exception {
    var body = productBody("Nullable", new BigDecimal("1.2300"), 0, "ACTIVE");
    body.put("description", null);
    var response = expect(call("POST", "/products", seller, body), 201);
    amount(response, "price", "1.23");
    assertThat(response.path("description").isNull()).isTrue();
  }

  @Test
  void productRolesAndSellerOwnership() throws Exception {
    UUID id = product("Owned", "10", 5);
    for (String token : List.of(user, seller, admin)) {
      expect(call("GET", "/products", token, null), 200);
      expect(call("GET", "/products/" + id, token, null), 200);
    }
    var payload = productBody("Updated", new BigDecimal("10"), 5, "ACTIVE");
    error(call("POST", "/products", user, payload), 403, "ACCESS_DENIED");
    error(call("PUT", "/products/" + id, user, payload), 403, "ACCESS_DENIED");
    error(call("DELETE", "/products/" + id, user, null), 403, "ACCESS_DENIED");
    error(call("PUT", "/products/" + id, otherSeller, payload), 403, "ACCESS_DENIED");
    error(call("DELETE", "/products/" + id, otherSeller, null), 403, "ACCESS_DENIED");
    payload.put("seller_id", otherSellerId);
    error(call("POST", "/products", seller, payload), 403, "ACCESS_DENIED");
    var adminCreated = expect(call("POST", "/products", admin, payload), 201);
    assertThat(adminCreated.path("seller_id").asText()).isEqualTo(otherSellerId.toString());
    expect(call("PUT", "/products/" + id, admin, payload), 200);
    expect(call("DELETE", "/products/" + id, admin, null), 204);
  }

  @Test
  void productAndOrderNotFoundAndStrictUuid() throws Exception {
    error(call("GET", "/products/" + UUID.randomUUID(), user, null), 404, "PRODUCT_NOT_FOUND");
    error(call("GET", "/orders/" + UUID.randomUUID(), user, null), 404, "ORDER_NOT_FOUND");
    error(call("GET", "/products/1-1-1-1-1", user, null), 400, "VALIDATION_ERROR");
  }

  @Test
  void registrationLoginAndRefreshRotation() throws Exception {
    var registered =
        expect(
            call(
                "POST",
                "/auth/register",
                null,
                Map.of("email", "New@example.test", "password", PASSWORD, "role", "USER")),
            201);
    assertThat(registered.has("password")).isFalse();
    assertThat(registered.has("password_hash")).isFalse();
    assertThat(
            jdbc.queryForObject(
                "SELECT password_hash FROM users WHERE id=?",
                String.class,
                UUID.fromString(registered.path("id").asText())))
        .isNotEqualTo(PASSWORD);
    error(
        call(
            "POST",
            "/auth/register",
            null,
            Map.of("email", "NEW@example.test", "password", PASSWORD, "role", "USER")),
        409,
        "EMAIL_ALREADY_EXISTS");
    error(
        call(
            "POST",
            "/auth/register",
            null,
            Map.of("email", "root@example.test", "password", PASSWORD, "role", "ADMIN")),
        400,
        "VALIDATION_ERROR");
    error(
        call("POST", "/auth/login", null, Map.of("email", "new@example.test", "password", "wrong")),
        401,
        "INVALID_CREDENTIALS");
    var tokens =
        expect(
            call(
                "POST",
                "/auth/login",
                null,
                Map.of("email", "new@example.test", "password", PASSWORD)),
            200);
    assertThat(tokens.path("expires_in").asInt()).isEqualTo(900);
    String access = tokens.path("access_token").asText(),
        refresh = tokens.path("refresh_token").asText();
    expect(call("GET", "/products", access, null), 200);
    error(call("GET", "/products", refresh, null), 401, "TOKEN_INVALID");
    error(
        call("POST", "/auth/refresh", null, Map.of("refresh_token", access)),
        401,
        "REFRESH_TOKEN_INVALID");
    var rotated =
        expect(call("POST", "/auth/refresh", null, Map.of("refresh_token", refresh)), 200);
    assertThat(rotated.path("refresh_token").asText()).isNotEqualTo(refresh);
    error(
        call("POST", "/auth/refresh", null, Map.of("refresh_token", refresh)),
        401,
        "REFRESH_TOKEN_INVALID");
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL", Long.class))
        .isEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "SELECT token_hash FROM refresh_tokens WHERE revoked_at IS NULL", String.class))
        .doesNotContain(refresh)
        .hasSize(64);
  }

  @Test
  void missingInvalidExpiredAndWrongTypeTokens() throws Exception {
    error(call("GET", "/products", null, null), 401, "TOKEN_INVALID");
    error(call("GET", "/products", "bad.token.value", null), 401, "TOKEN_INVALID");
    error(
        call(
            "GET",
            "/products",
            token(userId, "USER", "access", Instant.now().minusSeconds(1)),
            null),
        401,
        "TOKEN_EXPIRED");
    error(
        call(
            "GET",
            "/products",
            token(userId, "ADMINISTRATOR", "access", Instant.now().plusSeconds(100)),
            null),
        401,
        "TOKEN_INVALID");
    error(
        call(
            "POST",
            "/auth/refresh",
            null,
            Map.of(
                "refresh_token", token(userId, "USER", "refresh", Instant.now().minusSeconds(1)))),
        401,
        "REFRESH_TOKEN_INVALID");
  }

  @Test
  void orderReservesStockAndSnapshotsPrices() throws Exception {
    UUID id = product("Snapshot", "10.15", 10);
    var created = order(id, 3, user);
    amount(created, "total_amount", "30.45");
    assertThat(stock(id)).isEqualTo(7);
    expect(
        call(
            "PUT",
            "/products/" + id,
            seller,
            productBody("Changed", new BigDecimal("99.99"), 7, "ACTIVE")),
        200);
    var stored = expect(call("GET", "/orders/" + created.path("id").asText(), user, null), 200);
    amount(stored.path("items").get(0), "price_at_order", "10.15");
    amount(stored, "total_amount", "30.45");
    assertThat(count("user_operations")).isEqualTo(1);
    assertThat(count("order_items")).isEqualTo(1);
  }

  @Test
  void creationRateIsCheckedBeforeActiveOrder() throws Exception {
    UUID id = product("Rate", "10", 10);
    order(id, 1, user);
    var limited = call("POST", "/orders", user, orderBody(id, 1));
    error(limited, 429, "ORDER_LIMIT_EXCEEDED");
    assertThat(limited.getResponse().getHeader("Retry-After")).isNotBlank();
    age("CREATE_ORDER");
    error(call("POST", "/orders", user, orderBody(id, 1)), 409, "ORDER_HAS_ACTIVE");
    assertThat(count("orders")).isEqualTo(1);
    assertThat(stock(id)).isEqualTo(9);
  }

  @Test
  void shortagesListAllProductsAndDoNotReserve() throws Exception {
    UUID a = product("A", "10", 1), b = product("B", "20", 0);
    var response =
        error(
            call("POST", "/orders", user, Map.of("items", List.of(item(a, 2), item(b, 1)))),
            409,
            "INSUFFICIENT_STOCK");
    assertThat(response.path("details").path("products").size()).isEqualTo(2);
    assertThat(stock(a)).isEqualTo(1);
    assertThat(stock(b)).isZero();
    assertThat(count("orders")).isZero();
    assertThat(count("user_operations")).isZero();
  }

  @Test
  void unknownAndInactiveProducts() throws Exception {
    UUID id = product("Inactive", "1", 10);
    expect(call("DELETE", "/products/" + id, seller, null), 204);
    error(call("POST", "/orders", user, orderBody(UUID.randomUUID(), 1)), 404, "PRODUCT_NOT_FOUND");
    error(call("POST", "/orders", user, orderBody(id, 1)), 409, "PRODUCT_INACTIVE");
    assertThat(count("orders")).isZero();
  }

  @Test
  void invalidOrderInputNeverMutatesDatabase() throws Exception {
    UUID id = product("Validation", "1", 1000);
    for (Object request :
        List.of(
            Map.of("items", List.of()),
            orderBody(id, 0),
            orderBody(id, 1000),
            Map.of("items", List.of(item(id, 1), item(id, 2))),
            Map.of("items", List.of(item(id, 1)), "promo_code", "bad"),
            new Raw("{\"items\":[null]}"),
            Map.of("items", Collections.nCopies(51, item(id, 1))))) {
      error(call("POST", "/orders", user, request), 400, "VALIDATION_ERROR");
    }
    assertThat(stock(id)).isEqualTo(1000);
    assertThat(count("orders")).isZero();
    assertThat(count("user_operations")).isZero();
  }

  @Test
  void updateReturnsOldStockRepricesAndHasSeparateRate() throws Exception {
    UUID a = product("A", "10", 10), b = product("B", "25", 10);
    var created = order(a, 3, user);
    String id = created.path("id").asText();
    var updated = expect(call("PUT", "/orders/" + id, user, orderBody(b, 2)), 200);
    assertThat(stock(a)).isEqualTo(10);
    assertThat(stock(b)).isEqualTo(8);
    amount(updated, "total_amount", "50");
    error(call("PUT", "/orders/" + id, user, orderBody(a, 1)), 429, "ORDER_LIMIT_EXCEEDED");
    assertThat(stock(b)).isEqualTo(8);
    age("UPDATE_ORDER");
    expect(call("PUT", "/orders/" + id, user, orderBody(b, 10)), 200);
    assertThat(stock(b)).isZero();
  }

  @Test
  void failedUpdateRollsBackOldStockItemsAndAmounts() throws Exception {
    UUID a = product("A", "10", 10), b = product("B", "20", 0);
    String id = order(a, 3, user).path("id").asText();
    error(call("PUT", "/orders/" + id, user, orderBody(b, 1)), 409, "INSUFFICIENT_STOCK");
    assertThat(stock(a)).isEqualTo(7);
    assertThat(stock(b)).isZero();
    var unchanged = expect(call("GET", "/orders/" + id, user, null), 200);
    amount(unchanged, "total_amount", "30");
    assertThat(unchanged.path("items").get(0).path("product_id").asText()).isEqualTo(a.toString());
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM user_operations WHERE operation_type='UPDATE_ORDER'",
                Long.class))
        .isZero();
  }

  @Test
  void ownershipAndRoleMatrixForOrders() throws Exception {
    UUID p = product("Owner", "10", 10);
    String id = order(p, 1, user).path("id").asText();
    error(call("GET", "/orders/" + id, other, null), 403, "ORDER_OWNERSHIP_VIOLATION");
    error(call("PUT", "/orders/" + id, other, orderBody(p, 1)), 403, "ORDER_OWNERSHIP_VIOLATION");
    error(call("POST", "/orders/" + id + "/cancel", other, null), 403, "ORDER_OWNERSHIP_VIOLATION");
    error(call("POST", "/orders", seller, orderBody(p, 1)), 403, "ACCESS_DENIED");
    error(call("GET", "/orders/" + id, seller, null), 403, "ACCESS_DENIED");
    error(call("PUT", "/orders/" + id, seller, orderBody(p, 1)), 403, "ACCESS_DENIED");
    error(call("POST", "/orders/" + id + "/cancel", seller, null), 403, "ACCESS_DENIED");
    expect(call("GET", "/orders/" + id, admin, null), 200);
    expect(call("PUT", "/orders/" + id, admin, orderBody(p, 2)), 200);
    expect(call("POST", "/orders/" + id + "/cancel", admin, null), 200);
    expect(call("POST", "/orders", admin, orderBody(p, 1)), 201);
  }

  @ParameterizedTest
  @ValueSource(strings = {"CREATED", "PAYMENT_PENDING"})
  void cancellationRestoresStockAndPromoOnce(String state) throws Exception {
    UUID p = product("Cancel", "100", 10),
        promoId =
            UUID.fromString(promo("CANCEL10", "PERCENTAGE", "10", "0", 5).path("id").asText());
    String id = orderWithPromo(p, 3, "CANCEL10", user).path("id").asText();
    assertThat(uses(promoId)).isEqualTo(1);
    if (state.equals("PAYMENT_PENDING"))
      expect(call("PATCH", "/orders/" + id + "/status", admin, Map.of("status", state)), 200);
    assertThat(
            expect(call("POST", "/orders/" + id + "/cancel", user, null), 200)
                .path("status")
                .asText())
        .isEqualTo("CANCELED");
    assertThat(stock(p)).isEqualTo(10);
    assertThat(uses(promoId)).isZero();
    error(call("POST", "/orders/" + id + "/cancel", user, null), 409, "INVALID_STATE_TRANSITION");
    assertThat(stock(p)).isEqualTo(10);
    assertThat(uses(promoId)).isZero();
  }

  @Test
  void validStateMachineAndInvalidOperations() throws Exception {
    UUID p = product("State", "10", 10);
    String id = order(p, 1, user).path("id").asText();
    error(
        call("PATCH", "/orders/" + id + "/status", user, Map.of("status", "PAYMENT_PENDING")),
        403,
        "ACCESS_DENIED");
    error(
        call("PATCH", "/orders/" + id + "/status", admin, Map.of("status", "PAID")),
        409,
        "INVALID_STATE_TRANSITION");
    error(
        call("PATCH", "/orders/" + id + "/status", admin, Map.of("status", "CANCELED")),
        409,
        "INVALID_STATE_TRANSITION");
    for (String state : List.of("PAYMENT_PENDING", "PAID", "SHIPPED", "COMPLETED")) {
      assertThat(
              expect(
                      call("PATCH", "/orders/" + id + "/status", admin, Map.of("status", state)),
                      200)
                  .path("status")
                  .asText())
          .isEqualTo(state);
      error(call("PUT", "/orders/" + id, user, orderBody(p, 2)), 409, "INVALID_STATE_TRANSITION");
      if (!state.equals("PAYMENT_PENDING"))
        error(
            call("POST", "/orders/" + id + "/cancel", user, null), 409, "INVALID_STATE_TRANSITION");
    }
    age("CREATE_ORDER");
    expect(call("POST", "/orders", user, orderBody(p, 1)), 201);
  }

  @ParameterizedTest
  @CsvSource({"10,100.00,900.00", "70,700.00,300.00", "80,0.00,1000.00", "100,0.00,1000.00"})
  void percentageRule(String value, String discount, String total) throws Exception {
    UUID p = product("Percent", "1000", 10);
    promo("PERCENT1", "PERCENTAGE", value, "0", 1);
    var created = orderWithPromo(p, 1, "PERCENT1", user);
    amount(created, "discount_amount", discount);
    amount(created, "total_amount", total);
  }

  @Test
  void fixedDiscountNeverMakesTotalNegative() throws Exception {
    UUID p = product("Free", "10", 1);
    promo("FIXED100", "FIXED_AMOUNT", "100", "0", 1);
    var created = orderWithPromo(p, 1, "FIXED100", user);
    amount(created, "discount_amount", "10");
    amount(created, "total_amount", "0");
  }

  @Test
  void percentageRoundingNeverExceedsSeventyPercent() throws Exception {
    UUID p = product("One cent", "0.01", 1);
    promo("CENT0070", "PERCENTAGE", "70", "0", 1);
    var created = orderWithPromo(p, 1, "CENT0070", user);
    amount(created, "discount_amount", "0");
    amount(created, "total_amount", "0.01");
  }

  @Test
  void schemaAndSwaggerArePublic() throws Exception {
    var spec = call("GET", "/openapi/marketplace.yaml", null, null);
    assertThat(spec.getResponse().getStatus()).isEqualTo(200);
    assertThat(spec.getResponse().getContentAsString())
        .contains("openapi: 3.0.3", "ProductCreate:", "ProductUpdate:", "ProductResponse:");
    assertThat(call("GET", "/swagger-ui/index.html", null, null).getResponse().getStatus())
        .isEqualTo(200);
  }

  @Test
  void promoMinimumFailureRollsBackReservation() throws Exception {
    UUID p = product("Minimum", "10", 10),
        promoId =
            UUID.fromString(promo("MINIMUM1", "PERCENTAGE", "10", "100", 1).path("id").asText());
    error(
        call(
            "POST",
            "/orders",
            user,
            Map.of("items", List.of(item(p, 1)), "promo_code", "MINIMUM1")),
        422,
        "PROMO_CODE_MIN_AMOUNT");
    assertThat(stock(p)).isEqualTo(10);
    assertThat(uses(promoId)).isZero();
    assertThat(count("orders")).isZero();
    assertThat(count("user_operations")).isZero();
  }

  @ParameterizedTest
  @ValueSource(strings = {"MISSING1", "EXPIRED1", "FUTURE01", "DISABLED"})
  void invalidPromoVariants(String code) throws Exception {
    UUID p = product("Invalid promo", "10", 5);
    Instant now = Instant.now();
    if (code.equals("EXPIRED1"))
      promo(code, "PERCENTAGE", "10", "0", 1, now.minusSeconds(120), now.minusSeconds(60), true);
    if (code.equals("FUTURE01"))
      promo(code, "PERCENTAGE", "10", "0", 1, now.plusSeconds(60), now.plusSeconds(120), true);
    if (code.equals("DISABLED"))
      promo(code, "PERCENTAGE", "10", "0", 1, now.minusSeconds(60), now.plusSeconds(120), false);
    error(
        call("POST", "/orders", user, Map.of("items", List.of(item(p, 1)), "promo_code", code)),
        422,
        "PROMO_CODE_INVALID");
    assertThat(stock(p)).isEqualTo(5);
    assertThat(count("orders")).isZero();
  }

  @Test
  void updateKeepsOwnPromoUseThenRemovesBelowMinimum() throws Exception {
    UUID p = product("Reprice promo", "100", 10),
        promoId =
            UUID.fromString(promo("REPRICE1", "PERCENTAGE", "10", "200", 1).path("id").asText());
    String id = orderWithPromo(p, 3, "REPRICE1", user).path("id").asText();
    amount(expect(call("PUT", "/orders/" + id, user, orderBody(p, 2)), 200), "total_amount", "180");
    assertThat(uses(promoId)).isEqualTo(1);
    age("UPDATE_ORDER");
    var reduced = expect(call("PUT", "/orders/" + id, user, orderBody(p, 1)), 200);
    amount(reduced, "total_amount", "100");
    amount(reduced, "discount_amount", "0");
    assertThat(reduced.path("promo_code_id").isNull()).isTrue();
    assertThat(uses(promoId)).isZero();
  }

  @Test
  void updateWithExpiredPromoRollsBackEverything() throws Exception {
    UUID p = product("Expiry", "100", 10);
    UUID promoId =
        UUID.fromString(promo("EXPIREUP", "PERCENTAGE", "10", "0", 1).path("id").asText());
    String id = orderWithPromo(p, 2, "EXPIREUP", user).path("id").asText();
    jdbc.update(
        "UPDATE promo_codes SET valid_from=clock_timestamp()-interval '2"
            + " hours',valid_until=clock_timestamp()-interval '1 hour' WHERE id=?",
        promoId);
    error(call("PUT", "/orders/" + id, user, orderBody(p, 3)), 422, "PROMO_CODE_INVALID");
    assertThat(stock(p)).isEqualTo(8);
    assertThat(uses(promoId)).isEqualTo(1);
    amount(expect(call("GET", "/orders/" + id, user, null), 200), "total_amount", "180");
  }

  @Test
  void exhaustedPromoAndCancellationReleasesUse() throws Exception {
    UUID p = product("Exhaust", "10", 10),
        promoId =
            UUID.fromString(promo("ONEUSE01", "PERCENTAGE", "10", "0", 1).path("id").asText());
    String id = orderWithPromo(p, 1, "ONEUSE01", user).path("id").asText();
    error(
        call(
            "POST",
            "/orders",
            other,
            Map.of("items", List.of(item(p, 1)), "promo_code", "ONEUSE01")),
        422,
        "PROMO_CODE_INVALID");
    assertThat(stock(p)).isEqualTo(9);
    expect(call("POST", "/orders/" + id + "/cancel", user, null), 200);
    orderWithPromo(p, 1, "ONEUSE01", other);
    assertThat(uses(promoId)).isEqualTo(1);
  }

  List<MvcResult> race(Callable<MvcResult> first, Callable<MvcResult> second) throws Exception {
    var start = new CountDownLatch(1);
    try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
      var a =
          pool.submit(
              () -> {
                start.await();
                return first.call();
              });
      var b =
          pool.submit(
              () -> {
                start.await();
                return second.call();
              });
      start.countDown();
      return List.of(a.get(20, TimeUnit.SECONDS), b.get(20, TimeUnit.SECONDS));
    }
  }

  @Test
  void concurrentLastItemCannotBeOversold() throws Exception {
    UUID p = product("Last", "10", 1);
    var results =
        race(
            () -> call("POST", "/orders", user, orderBody(p, 1)),
            () -> call("POST", "/orders", other, orderBody(p, 1)));
    assertThat(results.stream().map(r -> r.getResponse().getStatus()).toList())
        .containsExactlyInAnyOrder(201, 409);
    assertThat(stock(p)).isZero();
    assertThat(count("orders")).isEqualTo(1);
    for (var r : results)
      if (r.getResponse().getStatus() == 409) error(r, 409, "INSUFFICIENT_STOCK");
  }

  @Test
  void concurrentRequestsForSameUserRespectRateAndActiveInvariant() throws Exception {
    UUID p = product("One active", "10", 10);
    var results =
        race(
            () -> call("POST", "/orders", user, orderBody(p, 1)),
            () -> call("POST", "/orders", user, orderBody(p, 1)));
    assertThat(results.stream().map(r -> r.getResponse().getStatus()).toList())
        .containsExactlyInAnyOrder(201, 429);
    assertThat(count("orders")).isEqualTo(1);
    assertThat(stock(p)).isEqualTo(9);
  }

  @Test
  void concurrentPromoLimitAcrossDifferentProducts() throws Exception {
    UUID a = product("Promo A", "10", 10),
        b = product("Promo B", "10", 10),
        promoId =
            UUID.fromString(promo("RACEPROM", "PERCENTAGE", "10", "0", 1).path("id").asText());
    var results =
        race(
            () ->
                call(
                    "POST",
                    "/orders",
                    user,
                    Map.of("items", List.of(item(a, 1)), "promo_code", "RACEPROM")),
            () ->
                call(
                    "POST",
                    "/orders",
                    other,
                    Map.of("items", List.of(item(b, 1)), "promo_code", "RACEPROM")));
    assertThat(results.stream().map(r -> r.getResponse().getStatus()).toList())
        .containsExactlyInAnyOrder(201, 422);
    assertThat(uses(promoId)).isEqualTo(1);
    assertThat(stock(a) + stock(b)).isEqualTo(19);
    assertThat(count("orders")).isEqualTo(1);
  }

  @Test
  void oppositeItemOrderDoesNotDeadlock() throws Exception {
    UUID a = product("Lock A", "10", 2), b = product("Lock B", "10", 2);
    var results =
        race(
            () -> call("POST", "/orders", user, Map.of("items", List.of(item(a, 1), item(b, 1)))),
            () -> call("POST", "/orders", other, Map.of("items", List.of(item(b, 1), item(a, 1)))));
    for (var result : results) expect(result, 201);
    assertThat(stock(a)).isZero();
    assertThat(stock(b)).isZero();
  }

  @Test
  void concurrentRefreshRotationAllowsOnlyOneSuccess() throws Exception {
    var tokens =
        expect(
            call(
                "POST",
                "/auth/login",
                null,
                Map.of("email", "user@example.test", "password", PASSWORD)),
            200);
    var body = Map.of("refresh_token", tokens.path("refresh_token").asText());
    var results =
        race(
            () -> call("POST", "/auth/refresh", null, body),
            () -> call("POST", "/auth/refresh", null, body));
    assertThat(results.stream().map(r -> r.getResponse().getStatus()).toList())
        .containsExactlyInAnyOrder(200, 401);
    assertThat(count("refresh_tokens")).isEqualTo(2);
  }

  @Test
  void jsonLogsHaveMandatoryFieldsAndMaskSecretsEvenOnForbiddenRequests() throws Exception {
    var login =
        call(
            "POST",
            "/auth/login",
            null,
            Map.of("email", "user@example.test", "password", PASSWORD));
    expect(login, 200);
    var forbidden =
        call(
            "POST", "/products", user, productBody("Forbidden", new BigDecimal("10"), 1, "ACTIVE"));
    error(forbidden, 403, "ACCESS_DENIED");
    var events =
        logs.list.stream()
            .map(
                e -> {
                  try {
                    return json.readTree(e.getFormattedMessage());
                  } catch (Exception ex) {
                    throw new AssertionError(ex);
                  }
                })
            .toList();
    for (var event : events) {
      for (String field :
          List.of(
              "request_id",
              "method",
              "endpoint",
              "status_code",
              "duration_ms",
              "user_id",
              "timestamp")) assertThat(event.has(field)).as(field).isTrue();
      UUID.fromString(event.path("request_id").asText());
      Instant.parse(event.path("timestamp").asText());
      assertThat(event.path("duration_ms").asDouble()).isGreaterThanOrEqualTo(0);
      assertThat(event.toString()).doesNotContain(PASSWORD);
    }
    var loginLog =
        events.stream()
            .filter(e -> e.path("endpoint").asText().equals("/auth/login"))
            .findFirst()
            .orElseThrow();
    assertThat(loginLog.path("request_body").path("password").asText()).isEqualTo("***");
    var deniedLog =
        events.stream()
            .filter(e -> e.path("endpoint").asText().equals("/products"))
            .findFirst()
            .orElseThrow();
    assertThat(deniedLog.path("request_body").path("name").asText()).isEqualTo("Forbidden");
    assertThat(deniedLog.path("user_id").asText()).isEqualTo(userId.toString());
  }

  @Test
  void missingPromoRightsAndDuplicatePromoCode() throws Exception {
    var body =
        Map.of(
            "code",
            "ROLEPROM",
            "discount_type",
            "PERCENTAGE",
            "discount_value",
            10,
            "min_order_amount",
            0,
            "max_uses",
            1,
            "valid_from",
            Instant.now().minusSeconds(60).toString(),
            "valid_until",
            Instant.now().plusSeconds(60).toString(),
            "active",
            true);
    error(call("POST", "/promo-codes", user, body), 403, "ACCESS_DENIED");
    expect(call("POST", "/promo-codes", seller, body), 201);
    error(call("POST", "/promo-codes", admin, body), 409, "PROMO_CODE_ALREADY_EXISTS");
  }

  @Test
  void amountOverflowRollsBackReservedStock() throws Exception {
    UUID p = product("Maximum decimal", "9999999999.99", 2);
    error(call("POST", "/orders", user, orderBody(p, 2)), 409, "AMOUNT_LIMIT_EXCEEDED");
    assertThat(stock(p)).isEqualTo(2);
    assertThat(count("orders")).isZero();
    assertThat(count("user_operations")).isZero();
  }

  @Test
  void storedRefreshExpiryIsCheckedAfterLock() throws Exception {
    var tokens =
        expect(
            call(
                "POST",
                "/auth/login",
                null,
                Map.of("email", "user@example.test", "password", PASSWORD)),
            200);
    jdbc.update("UPDATE refresh_tokens SET expires_at=clock_timestamp()-interval '1 second'");
    error(
        call(
            "POST",
            "/auth/refresh",
            null,
            Map.of("refresh_token", tokens.path("refresh_token").asText())),
        401,
        "REFRESH_TOKEN_INVALID");
  }

  @Test
  void mediaTypeAndAcceptErrorsUseTheContract() throws Exception {
    var unsupported =
        mvc.perform(
                post("/products")
                    .header("Authorization", "Bearer " + seller)
                    .contentType(MediaType.TEXT_PLAIN)
                    .content("not json"))
            .andReturn();
    error(unsupported, 400, "VALIDATION_ERROR");
    var unacceptable =
        mvc.perform(
                get("/products")
                    .header("Authorization", "Bearer " + user)
                    .accept(MediaType.TEXT_PLAIN))
            .andReturn();
    error(unacceptable, 400, "VALIDATION_ERROR");
  }

  @Test
  void stockCanBeReturnedEvenAfterProductWasArchived() throws Exception {
    UUID p = product("Archived reserve", "10", 3);
    String id = order(p, 2, user).path("id").asText();
    expect(call("DELETE", "/products/" + p, seller, null), 204);
    error(call("PUT", "/orders/" + id, user, orderBody(p, 1)), 409, "PRODUCT_INACTIVE");
    assertThat(stock(p)).isEqualTo(1);
    expect(call("POST", "/orders/" + id + "/cancel", user, null), 200);
    assertThat(stock(p)).isEqualTo(3);
  }
}
