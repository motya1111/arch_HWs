package ru.marketplace.api;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;
import ru.marketplace.generated.api.PromosApi;
import ru.marketplace.generated.model.*;
import ru.marketplace.service.PromoService;

@RestController
public class PromosController implements PromosApi {
  private final PromoService promos;

  public PromosController(PromoService promos) {
    this.promos = promos;
  }

  @Override
  public ResponseEntity<PromoCodeResponse> createPromoCode(PromoCodeCreate request) {
    return ResponseEntity.status(201).body(promos.create(request));
  }
}
