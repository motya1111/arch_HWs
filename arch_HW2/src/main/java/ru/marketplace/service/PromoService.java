package ru.marketplace.service;

import java.math.*;
import java.time.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.marketplace.error.ApiException;
import ru.marketplace.generated.model.*;
import ru.marketplace.persistence.MarketplaceRepository;

@Service
public class PromoService {
  private final MarketplaceRepository repository;
  private final Clock clock;

  public PromoService(MarketplaceRepository repository, Clock clock) {
    this.repository = repository;
    this.clock = clock;
  }

  @Transactional
  public PromoCodeResponse create(PromoCodeCreate request) {
    if (!request.getValidUntil().isAfter(request.getValidFrom()))
      throw ApiException.validation("valid_until", "must be after valid_from");
    if (request.getDiscountType() == DiscountType.PERCENTAGE
        && request.getDiscountValue().compareTo(new BigDecimal("100")) > 0)
      throw ApiException.validation("discount_value", "percentage must not exceed 100");
    try {
      return repository.insertPromo(request);
    } catch (DuplicateKeyException ex) {
      throw new ApiException(409, ErrorCode.PROMO_CODE_ALREADY_EXISTS, "Promo code already exists");
    }
  }

  public void validate(PromoCodeResponse promo, boolean alreadyApplied) {
    Instant now = clock.instant();
    boolean exhausted =
        alreadyApplied
            ? promo.getCurrentUses() > promo.getMaxUses()
            : promo.getCurrentUses() >= promo.getMaxUses();
    if (!promo.getActive()
        || exhausted
        || now.isBefore(promo.getValidFrom().toInstant())
        || now.isAfter(promo.getValidUntil().toInstant())) throw invalid();
  }

  public BigDecimal discount(PromoCodeResponse promo, BigDecimal subtotal) {
    BigDecimal discount;
    if (promo.getDiscountType() == DiscountType.FIXED_AMOUNT)
      discount = promo.getDiscountValue().min(subtotal);
    else {
      // Over 70% means full price.
      discount =
          promo.getDiscountValue().compareTo(new BigDecimal("70")) > 0
              ? BigDecimal.ZERO
              : subtotal.multiply(promo.getDiscountValue()).divide(new BigDecimal("100"));
    }
    BigDecimal rounded = discount.setScale(2, RoundingMode.HALF_UP);
    if (promo.getDiscountType() == DiscountType.PERCENTAGE) {
      // Keep the 70% limit after rounding.
      rounded =
          rounded.min(subtotal.multiply(new BigDecimal("0.70")).setScale(2, RoundingMode.DOWN));
    }
    return rounded;
  }

  public static ApiException invalid() {
    return new ApiException(422, ErrorCode.PROMO_CODE_INVALID, "Promo code is unavailable");
  }
}
