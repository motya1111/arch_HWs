package ru.marketplace.api;

import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;
import ru.marketplace.generated.api.OrdersApi;
import ru.marketplace.generated.model.*;
import ru.marketplace.security.Actor;
import ru.marketplace.service.OrderService;

@RestController
public class OrdersController implements OrdersApi {
  private final OrderService orders;

  public OrdersController(OrderService orders) {
    this.orders = orders;
  }

  @Override
  public ResponseEntity<OrderResponse> createOrder(OrderCreate request) {
    return ResponseEntity.status(201).body(orders.create(request, Actor.current()));
  }

  @Override
  public ResponseEntity<OrderResponse> getOrder(UUID id) {
    return ResponseEntity.ok(orders.get(id, Actor.current()));
  }

  @Override
  public ResponseEntity<OrderResponse> updateOrder(UUID id, OrderUpdate request) {
    return ResponseEntity.ok(orders.update(id, request, Actor.current()));
  }

  @Override
  public ResponseEntity<OrderResponse> cancelOrder(UUID id) {
    return ResponseEntity.ok(orders.cancel(id, Actor.current()));
  }

  @Override
  public ResponseEntity<OrderResponse> changeOrderStatus(UUID id, OrderStatusUpdate request) {
    return ResponseEntity.ok(orders.changeStatus(id, request.getStatus(), Actor.current()));
  }
}
