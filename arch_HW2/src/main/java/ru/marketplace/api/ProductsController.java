package ru.marketplace.api;

import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;
import ru.marketplace.generated.api.ProductsApi;
import ru.marketplace.generated.model.*;
import ru.marketplace.security.Actor;
import ru.marketplace.service.ProductService;

@RestController
public class ProductsController implements ProductsApi {
  private final ProductService products;

  public ProductsController(ProductService products) {
    this.products = products;
  }

  @Override
  public ResponseEntity<ProductResponse> createProduct(ProductCreate request) {
    return ResponseEntity.status(201).body(products.create(request, Actor.current()));
  }

  @Override
  public ResponseEntity<ProductResponse> getProduct(UUID id) {
    return ResponseEntity.ok(products.get(id));
  }

  @Override
  public ResponseEntity<ProductPage> listProducts(
      Integer page, Integer size, ProductStatus status, String category) {
    return ResponseEntity.ok(products.list(page, size, status, category));
  }

  @Override
  public ResponseEntity<ProductResponse> updateProduct(UUID id, ProductUpdate request) {
    return ResponseEntity.ok(products.update(id, request, Actor.current()));
  }

  @Override
  public ResponseEntity<Void> archiveProduct(UUID id) {
    products.archive(id, Actor.current());
    return ResponseEntity.noContent().build();
  }
}
