package ru.marketplace.service;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;
import ru.marketplace.error.ApiException;
import ru.marketplace.generated.model.*;
import ru.marketplace.persistence.MarketplaceRepository;
import ru.marketplace.security.Actor;

@Service
public class ProductService {
  private final MarketplaceRepository repository;

  public ProductService(MarketplaceRepository repository) {
    this.repository = repository;
  }

  @Transactional
  public ProductResponse create(ProductCreate request, Actor actor) {
    return repository.insertProduct(
        request, resolveSeller(request.getSellerId(), actor.id(), actor));
  }

  @Transactional(readOnly = true)
  public ProductResponse get(UUID id) {
    return repository.product(id).orElseThrow(ProductService::notFound);
  }

  @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
  public ProductPage list(int page, int size, ProductStatus status, String category) {
    return repository.products(page, size, status, category);
  }

  @Transactional
  public ProductResponse update(UUID id, ProductUpdate request, Actor actor) {
    var old = repository.lockProducts(List.of(id)).get(id);
    if (old == null) throw notFound();
    checkOwner(old, actor);
    if (request.getStock().longValue() + repository.returnableStock(id) > Integer.MAX_VALUE)
      throw ApiException.validation("stock", "must leave room for returning active reservations");
    return repository.updateProduct(
        id, request, resolveSeller(request.getSellerId(), old.getSellerId(), actor));
  }

  @Transactional
  public void archive(UUID id, Actor actor) {
    var old = repository.lockProducts(List.of(id)).get(id);
    if (old == null) throw notFound();
    checkOwner(old, actor);
    repository.archive(id);
  }

  private UUID resolveSeller(UUID requested, UUID fallback, Actor actor) {
    UUID selected = requested == null ? fallback : requested;
    if (!actor.admin() && !selected.equals(actor.id()))
      throw new ApiException(
          403, ErrorCode.ACCESS_DENIED, "Seller can only manage their own products");
    if (repository
        .accountById(selected)
        .filter(a -> a.role() == Role.SELLER || a.role() == Role.ADMIN)
        .isEmpty())
      throw ApiException.validation("seller_id", "must identify an existing SELLER or ADMIN");
    return selected;
  }

  private void checkOwner(ProductResponse product, Actor actor) {
    if (!actor.admin() && !product.getSellerId().equals(actor.id()))
      throw new ApiException(403, ErrorCode.ACCESS_DENIED, "Product belongs to another seller");
  }

  public static ApiException notFound() {
    return new ApiException(404, ErrorCode.PRODUCT_NOT_FOUND, "Product not found");
  }
}
