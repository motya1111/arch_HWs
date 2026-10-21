package ru.marketplace.persistence;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.*;
import org.springframework.stereotype.Repository;
import ru.marketplace.generated.model.*;

@Repository
public class MarketplaceRepository {
  private final JdbcTemplate jdbc;

  public MarketplaceRepository(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public record Account(
      UUID id, String email, String passwordHash, Role role, OffsetDateTime createdAt) {
    public UserResponse response() {
      return new UserResponse().id(id).email(email).role(role).createdAt(createdAt);
    }
  }

  private final RowMapper<Account> accountMapper =
      (rs, n) ->
          new Account(
              uuid(rs, "id"),
              rs.getString("email"),
              rs.getString("password_hash"),
              Role.fromValue(rs.getString("role")),
              time(rs, "created_at"));
  private final RowMapper<ProductResponse> productMapper =
      (rs, n) ->
          new ProductResponse()
              .id(uuid(rs, "id"))
              .name(rs.getString("name"))
              .description(rs.getString("description"))
              .price(rs.getBigDecimal("price"))
              .stock(rs.getInt("stock"))
              .category(rs.getString("category"))
              .status(ProductStatus.fromValue(rs.getString("status")))
              .sellerId(uuid(rs, "seller_id"))
              .createdAt(time(rs, "created_at"))
              .updatedAt(time(rs, "updated_at"));
  private final RowMapper<PromoCodeResponse> promoMapper =
      (rs, n) ->
          new PromoCodeResponse()
              .id(uuid(rs, "id"))
              .code(rs.getString("code"))
              .discountType(DiscountType.fromValue(rs.getString("discount_type")))
              .discountValue(rs.getBigDecimal("discount_value"))
              .minOrderAmount(rs.getBigDecimal("min_order_amount"))
              .maxUses(rs.getInt("max_uses"))
              .currentUses(rs.getInt("current_uses"))
              .validFrom(time(rs, "valid_from"))
              .validUntil(time(rs, "valid_until"))
              .active(rs.getBoolean("active"));
  private final RowMapper<OrderResponse> orderMapper =
      (rs, n) ->
          new OrderResponse()
              .id(uuid(rs, "id"))
              .userId(uuid(rs, "user_id"))
              .status(OrderStatus.fromValue(rs.getString("status")))
              .promoCodeId(uuid(rs, "promo_code_id"))
              .totalAmount(rs.getBigDecimal("total_amount"))
              .discountAmount(rs.getBigDecimal("discount_amount"))
              .createdAt(time(rs, "created_at"))
              .updatedAt(time(rs, "updated_at"));

  private static UUID uuid(ResultSet rs, String name) throws SQLException {
    return rs.getObject(name, UUID.class);
  }

  private static OffsetDateTime time(ResultSet rs, String name) throws SQLException {
    return rs.getObject(name, OffsetDateTime.class);
  }

  public Optional<Account> accountByEmail(String email) {
    return jdbc
        .query("SELECT * FROM users WHERE lower(email)=lower(?)", accountMapper, email)
        .stream()
        .findFirst();
  }

  public Optional<Account> accountById(UUID id) {
    return jdbc.query("SELECT * FROM users WHERE id=?", accountMapper, id).stream().findFirst();
  }

  public Account insertAccount(String email, String hash, Role role) {
    UUID id = UUID.randomUUID();
    jdbc.update(
        "INSERT INTO users(id,email,password_hash,role) VALUES (?,?,?,CAST(? AS user_role))",
        id,
        email,
        hash,
        role.getValue());
    return accountById(id).orElseThrow();
  }

  // Compatible with FK KEY SHARE locks.
  public void lockUser(UUID userId) {
    jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR NO KEY UPDATE", UUID.class, userId);
  }

  public Optional<ProductResponse> product(UUID id) {
    return jdbc.query("SELECT * FROM products WHERE id=?", productMapper, id).stream().findFirst();
  }

  public Map<UUID, ProductResponse> lockProducts(Collection<UUID> ids) {
    if (ids.isEmpty()) return Map.of();
    var sorted = ids.stream().distinct().sorted().toList();
    String placeholders = String.join(",", Collections.nCopies(sorted.size(), "?"));
    var products =
        jdbc.query(
            "SELECT * FROM products WHERE id IN (" + placeholders + ") ORDER BY id FOR UPDATE",
            productMapper,
            sorted.toArray());
    var result = new LinkedHashMap<UUID, ProductResponse>();
    products.forEach(p -> result.put(p.getId(), p));
    return result;
  }

  public ProductResponse insertProduct(ProductCreate request, UUID sellerId) {
    UUID id = UUID.randomUUID();
    jdbc.update(
        "INSERT INTO products(id,name,description,price,stock,category,status,seller_id) VALUES"
            + " (?,?,?,?,?,?,CAST(? AS product_status),?)",
        id,
        request.getName(),
        request.getDescription(),
        request.getPrice(),
        request.getStock(),
        request.getCategory(),
        request.getStatus().getValue(),
        sellerId);
    return product(id).orElseThrow();
  }

  public ProductResponse updateProduct(UUID id, ProductUpdate request, UUID sellerId) {
    jdbc.update(
        "UPDATE products SET name=?,description=?,price=?,stock=?,category=?,status=CAST(? AS"
            + " product_status),seller_id=? WHERE id=?",
        request.getName(),
        request.getDescription(),
        request.getPrice(),
        request.getStock(),
        request.getCategory(),
        request.getStatus().getValue(),
        sellerId,
        id);
    return product(id).orElseThrow();
  }

  public void archive(UUID id) {
    jdbc.update("UPDATE products SET status='ARCHIVED' WHERE id=? AND status<>'ARCHIVED'", id);
  }

  public ProductPage products(int page, int size, ProductStatus status, String category) {
    var args = new ArrayList<Object>();
    String where = " WHERE true";
    if (status != null) {
      where += " AND status=CAST(? AS product_status)";
      args.add(status.getValue());
    }
    if (category != null) {
      where += " AND category=?";
      args.add(category);
    }
    Long total =
        jdbc.queryForObject("SELECT count(*) FROM products" + where, Long.class, args.toArray());
    args.add(size);
    args.add((long) page * size);
    return new ProductPage()
        .content(
            jdbc.query(
                "SELECT * FROM products" + where + " ORDER BY created_at,id LIMIT ? OFFSET ?",
                productMapper,
                args.toArray()))
        .totalElements(total)
        .page(page)
        .size(size);
  }

  public void adjustStock(UUID id, int delta) {
    jdbc.update("UPDATE products SET stock=stock+? WHERE id=?", delta, id);
  }

  public long returnableStock(UUID productId) {
    return jdbc.queryForObject(
        "SELECT COALESCE(SUM(i.quantity),0) FROM order_items i JOIN orders o ON o.id=i.order_id"
            + " WHERE i.product_id=? AND o.status IN ('CREATED','PAYMENT_PENDING')",
        Long.class,
        productId);
  }

  public boolean hasActiveOrder(UUID userId) {
    return Boolean.TRUE.equals(
        jdbc.queryForObject(
            "SELECT EXISTS(SELECT 1 FROM orders WHERE user_id=? AND status IN"
                + " ('CREATED','PAYMENT_PENDING'))",
            Boolean.class,
            userId));
  }

  public Optional<Instant> lastOperation(UUID userId, String type) {
    return jdbc
        .query(
            "SELECT created_at FROM user_operations WHERE user_id=? AND operation_type=CAST(? AS"
                + " operation_type) ORDER BY created_at DESC LIMIT 1",
            (rs, n) -> time(rs, "created_at").toInstant(),
            userId,
            type)
        .stream()
        .findFirst();
  }

  public void operation(UUID userId, String type, Instant now) {
    jdbc.update(
        "INSERT INTO user_operations(id,user_id,operation_type,created_at) VALUES (?,?,CAST(? AS"
            + " operation_type),?)",
        UUID.randomUUID(),
        userId,
        type,
        OffsetDateTime.ofInstant(now, ZoneOffset.UTC));
  }

  public Optional<OrderResponse> order(UUID id, boolean lock) {
    var found =
        jdbc
            .query("SELECT * FROM orders WHERE id=?" + (lock ? " FOR UPDATE" : ""), orderMapper, id)
            .stream()
            .findFirst();
    found.ifPresent(
        o ->
            o.setItems(
                jdbc.query(
                    "SELECT * FROM order_items WHERE order_id=? ORDER BY product_id",
                    (rs, n) ->
                        new OrderItemResponse()
                            .id(uuid(rs, "id"))
                            .productId(uuid(rs, "product_id"))
                            .quantity(rs.getInt("quantity"))
                            .priceAtOrder(rs.getBigDecimal("price_at_order")),
                    id)));
    return found;
  }

  public void insertOrder(
      UUID id, UUID userId, UUID promoId, BigDecimal total, BigDecimal discount) {
    jdbc.update(
        "INSERT INTO orders(id,user_id,status,promo_code_id,total_amount,discount_amount) VALUES"
            + " (?,?,'CREATED',?,?,?)",
        id,
        userId,
        promoId,
        total,
        discount);
  }

  public void replaceItems(
      UUID orderId, List<OrderItemInput> items, Map<UUID, ProductResponse> products) {
    jdbc.update("DELETE FROM order_items WHERE order_id=?", orderId);
    for (var item : items)
      jdbc.update(
          "INSERT INTO order_items(id,order_id,product_id,quantity,price_at_order) VALUES"
              + " (?,?,?,?,?)",
          UUID.randomUUID(),
          orderId,
          item.getProductId(),
          item.getQuantity(),
          products.get(item.getProductId()).getPrice());
  }

  public void updateOrderAmounts(
      UUID orderId, UUID promoId, BigDecimal total, BigDecimal discount) {
    jdbc.update(
        "UPDATE orders SET promo_code_id=?,total_amount=?,discount_amount=? WHERE id=?",
        promoId,
        total,
        discount,
        orderId);
  }

  public void changeStatus(UUID orderId, OrderStatus status) {
    jdbc.update(
        "UPDATE orders SET status=CAST(? AS order_status) WHERE id=?", status.getValue(), orderId);
  }

  public Optional<PromoCodeResponse> lockPromoByCode(String code) {
    return jdbc
        .query("SELECT * FROM promo_codes WHERE code=? FOR UPDATE", promoMapper, code)
        .stream()
        .findFirst();
  }

  public PromoCodeResponse lockPromoById(UUID id) {
    return jdbc.queryForObject("SELECT * FROM promo_codes WHERE id=? FOR UPDATE", promoMapper, id);
  }

  public void adjustPromoUses(UUID id, int delta) {
    jdbc.update("UPDATE promo_codes SET current_uses=current_uses+? WHERE id=?", delta, id);
  }

  public PromoCodeResponse insertPromo(PromoCodeCreate request) {
    UUID id = UUID.randomUUID();
    jdbc.update(
        "INSERT INTO"
            + " promo_codes(id,code,discount_type,discount_value,min_order_amount,max_uses,valid_from,valid_until,active)"
            + " VALUES (?,?,CAST(? AS discount_type),?,?,?,?,?,?)",
        id,
        request.getCode(),
        request.getDiscountType().getValue(),
        request.getDiscountValue(),
        request.getMinOrderAmount(),
        request.getMaxUses(),
        request.getValidFrom(),
        request.getValidUntil(),
        request.getActive());
    return jdbc.queryForObject("SELECT * FROM promo_codes WHERE id=?", promoMapper, id);
  }

  public void insertRefresh(UUID id, UUID userId, String hash, Instant expiresAt) {
    jdbc.update(
        "INSERT INTO refresh_tokens(id,user_id,token_hash,expires_at) VALUES (?,?,?,?)",
        id,
        userId,
        hash,
        OffsetDateTime.ofInstant(expiresAt, ZoneOffset.UTC));
  }

  public record RefreshSession(
      UUID userId, String tokenHash, Instant expiresAt, Instant revokedAt) {}

  public Optional<RefreshSession> lockRefresh(UUID id) {
    return jdbc
        .query(
            "SELECT * FROM refresh_tokens WHERE id=? FOR UPDATE",
            (rs, n) ->
                new RefreshSession(
                    uuid(rs, "user_id"),
                    rs.getString("token_hash"),
                    time(rs, "expires_at").toInstant(),
                    time(rs, "revoked_at") == null ? null : time(rs, "revoked_at").toInstant()),
            id)
        .stream()
        .findFirst();
  }

  public void revokeRefresh(UUID id, Instant now) {
    jdbc.update(
        "UPDATE refresh_tokens SET revoked_at=? WHERE id=?",
        OffsetDateTime.ofInstant(now, ZoneOffset.UTC),
        id);
  }
}
