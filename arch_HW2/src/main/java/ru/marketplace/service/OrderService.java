package ru.marketplace.service;

import java.math.*;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.marketplace.error.ApiException;
import ru.marketplace.generated.model.*;
import ru.marketplace.persistence.MarketplaceRepository;
import ru.marketplace.security.Actor;

@Service
public class OrderService {
  private static final BigDecimal MAX_AMOUNT = new BigDecimal("9999999999.99");
  private static final Map<OrderStatus, OrderStatus> NEXT =
      Map.of(
          OrderStatus.CREATED,
          OrderStatus.PAYMENT_PENDING,
          OrderStatus.PAYMENT_PENDING,
          OrderStatus.PAID,
          OrderStatus.PAID,
          OrderStatus.SHIPPED,
          OrderStatus.SHIPPED,
          OrderStatus.COMPLETED);
  private final MarketplaceRepository repository;
  private final PromoService promos;
  private final Clock clock;
  private final Duration rateInterval;

  public OrderService(
      MarketplaceRepository repository,
      PromoService promos,
      Clock clock,
      @Value("${marketplace.order-rate-limit-minutes}") long minutes) {
    if (minutes < 0)
      throw new IllegalArgumentException("ORDER_RATE_LIMIT_MINUTES must be nonnegative");
    this.repository = repository;
    this.promos = promos;
    this.clock = clock;
    this.rateInterval = Duration.ofMinutes(minutes);
  }

  @Transactional
  public OrderResponse create(OrderCreate request, Actor actor) {
    repository.lockUser(actor.id());
    checkRate(actor.id(), "CREATE_ORDER");
    if (repository.hasActiveOrder(actor.id()))
      throw new ApiException(409, ErrorCode.ORDER_HAS_ACTIVE, "User already has an active order");
    var products =
        repository.lockProducts(
            request.getItems().stream().map(OrderItemInput::getProductId).toList());
    validateCatalog(request.getItems(), products);
    checkStock(request.getItems(), products);
    reserve(request.getItems());
    BigDecimal subtotal = subtotal(request.getItems(), products),
        discount = BigDecimal.ZERO.setScale(2);
    UUID promoId = null;
    if (request.getPromoCode() != null) {
      var promo =
          repository.lockPromoByCode(request.getPromoCode()).orElseThrow(PromoService::invalid);
      promos.validate(promo, false);
      if (subtotal.compareTo(promo.getMinOrderAmount()) < 0)
        throw new ApiException(
            422,
            ErrorCode.PROMO_CODE_MIN_AMOUNT,
            "Order amount is below promo minimum",
            Map.of("subtotal", subtotal, "min_order_amount", promo.getMinOrderAmount()));
      discount = promos.discount(promo, subtotal);
      promoId = promo.getId();
      repository.adjustPromoUses(promoId, 1);
    }
    UUID orderId = UUID.randomUUID();
    repository.insertOrder(orderId, actor.id(), promoId, subtotal.subtract(discount), discount);
    repository.replaceItems(orderId, request.getItems(), products);
    repository.operation(actor.id(), "CREATE_ORDER", clock.instant());
    return repository.order(orderId, false).orElseThrow();
  }

  @Transactional(
      readOnly = true,
      isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
  public OrderResponse get(UUID id, Actor actor) {
    var order = repository.order(id, false).orElseThrow(OrderService::notFound);
    checkOwner(order, actor);
    return order;
  }

  @Transactional
  public OrderResponse update(UUID id, OrderUpdate request, Actor actor) {
    var order = lockOwnedOrder(id, actor);
    if (order.getStatus() != OrderStatus.CREATED) throw invalidState();
    checkRate(order.getUserId(), "UPDATE_ORDER");
    var ids = new HashSet<UUID>();
    order.getItems().forEach(i -> ids.add(i.getProductId()));
    request.getItems().forEach(i -> ids.add(i.getProductId()));
    var products = repository.lockProducts(ids);
    // Restore SQL stock and the locked snapshot.
    for (var item : order.getItems()) {
      repository.adjustStock(item.getProductId(), item.getQuantity());
      var product = products.get(item.getProductId());
      product.setStock(Math.addExact(product.getStock(), item.getQuantity()));
    }
    validateCatalog(request.getItems(), products);
    checkStock(request.getItems(), products);
    reserve(request.getItems());
    BigDecimal subtotal = subtotal(request.getItems(), products),
        discount = BigDecimal.ZERO.setScale(2);
    UUID promoId = order.getPromoCodeId();
    if (promoId != null) {
      var promo = repository.lockPromoById(promoId);
      promos.validate(promo, true);
      if (subtotal.compareTo(promo.getMinOrderAmount()) < 0) {
        repository.adjustPromoUses(promoId, -1);
        promoId = null;
      } else discount = promos.discount(promo, subtotal);
    }
    repository.replaceItems(id, request.getItems(), products);
    repository.updateOrderAmounts(id, promoId, subtotal.subtract(discount), discount);
    repository.operation(order.getUserId(), "UPDATE_ORDER", clock.instant());
    return repository.order(id, false).orElseThrow();
  }

  @Transactional
  public OrderResponse cancel(UUID id, Actor actor) {
    var order = lockOwnedOrder(id, actor);
    if (order.getStatus() != OrderStatus.CREATED
        && order.getStatus() != OrderStatus.PAYMENT_PENDING) throw invalidState();
    repository.lockProducts(
        order.getItems().stream().map(OrderItemResponse::getProductId).toList());
    for (var item : order.getItems())
      repository.adjustStock(item.getProductId(), item.getQuantity());
    if (order.getPromoCodeId() != null) {
      repository.lockPromoById(order.getPromoCodeId());
      repository.adjustPromoUses(order.getPromoCodeId(), -1);
    }
    repository.changeStatus(id, OrderStatus.CANCELED);
    return repository.order(id, false).orElseThrow();
  }

  @Transactional
  public OrderResponse changeStatus(UUID id, OrderStatus target, Actor actor) {
    var order = lockOwnedOrder(id, actor);
    if (NEXT.get(order.getStatus()) != target) throw invalidState();
    repository.changeStatus(id, target);
    return repository.order(id, false).orElseThrow();
  }

  private OrderResponse lockOwnedOrder(UUID id, Actor actor) {
    var initial = repository.order(id, false).orElseThrow(OrderService::notFound);
    checkOwner(initial, actor);
    // Lock order: owner → order → sorted products → promo.
    repository.lockUser(initial.getUserId());
    var locked = repository.order(id, true).orElseThrow(OrderService::notFound);
    checkOwner(locked, actor);
    return locked;
  }

  private void checkOwner(OrderResponse order, Actor actor) {
    if (!actor.admin() && !order.getUserId().equals(actor.id()))
      throw new ApiException(
          403, ErrorCode.ORDER_OWNERSHIP_VIOLATION, "Order belongs to another user");
  }

  private void checkRate(UUID userId, String type) {
    repository
        .lastOperation(userId, type)
        .ifPresent(
            last -> {
              Instant next = last.plus(rateInterval), now = clock.instant();
              if (now.isBefore(next)) {
                long seconds = Math.max(1, (Duration.between(now, next).toMillis() + 999) / 1000);
                throw new ApiException(
                    429,
                    ErrorCode.ORDER_LIMIT_EXCEEDED,
                    "Order operation rate limit exceeded",
                    Map.of("retry_after_seconds", seconds, "operation_type", type));
              }
            });
  }

  private void validateCatalog(List<OrderItemInput> items, Map<UUID, ProductResponse> products) {
    for (var item : items)
      if (!products.containsKey(item.getProductId()))
        throw new ApiException(
            404,
            ErrorCode.PRODUCT_NOT_FOUND,
            "Product not found",
            Map.of("product_id", item.getProductId()));
    for (var item : items)
      if (products.get(item.getProductId()).getStatus() != ProductStatus.ACTIVE)
        throw new ApiException(
            409,
            ErrorCode.PRODUCT_INACTIVE,
            "Product is not ACTIVE",
            Map.of("product_id", item.getProductId()));
  }

  private void checkStock(List<OrderItemInput> items, Map<UUID, ProductResponse> products) {
    var shortages = new ArrayList<Map<String, Object>>();
    for (var item : items) {
      int available = products.get(item.getProductId()).getStock();
      if (available < item.getQuantity())
        shortages.add(
            Map.of(
                "product_id",
                item.getProductId(),
                "requested_quantity",
                item.getQuantity(),
                "available_stock",
                available));
    }
    if (!shortages.isEmpty())
      throw new ApiException(
          409, ErrorCode.INSUFFICIENT_STOCK, "Insufficient stock", Map.of("products", shortages));
  }

  private void reserve(List<OrderItemInput> items) {
    for (var item : items) repository.adjustStock(item.getProductId(), -item.getQuantity());
  }

  private BigDecimal subtotal(List<OrderItemInput> items, Map<UUID, ProductResponse> products) {
    var total =
        items.stream()
            .map(
                i ->
                    products
                        .get(i.getProductId())
                        .getPrice()
                        .multiply(BigDecimal.valueOf(i.getQuantity())))
            .reduce(BigDecimal.ZERO, BigDecimal::add)
            .setScale(2, RoundingMode.UNNECESSARY);
    if (total.compareTo(MAX_AMOUNT) > 0)
      throw new ApiException(
          409, ErrorCode.AMOUNT_LIMIT_EXCEEDED, "Order subtotal exceeds DECIMAL(12,2)");
    return total;
  }

  public static ApiException notFound() {
    return new ApiException(404, ErrorCode.ORDER_NOT_FOUND, "Order not found");
  }

  private static ApiException invalidState() {
    return new ApiException(
        409,
        ErrorCode.INVALID_STATE_TRANSITION,
        "Operation is not allowed in the current order state");
  }
}
