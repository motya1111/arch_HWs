package ru.marketplace;

import static org.assertj.core.api.Assertions.*;

import java.time.*;
import org.junit.jupiter.api.Test;
import ru.marketplace.error.ApiException;
import ru.marketplace.generated.model.*;
import ru.marketplace.service.PromoService;

class PromoBoundaryTest {
  @Test
  void validityWindowIncludesBothEndpointsAndExcludesOutsideInstants() {
    Instant from = Instant.parse("2026-01-01T00:00:00Z"), until = from.plusSeconds(60);
    var promo =
        new PromoCodeResponse()
            .active(true)
            .currentUses(0)
            .maxUses(1)
            .validFrom(from.atOffset(ZoneOffset.UTC))
            .validUntil(until.atOffset(ZoneOffset.UTC));
    for (Instant now : new Instant[] {from, until}) {
      var service = new PromoService(null, Clock.fixed(now, ZoneOffset.UTC));
      assertThatCode(() -> service.validate(promo, false)).doesNotThrowAnyException();
    }
    for (Instant now : new Instant[] {from.minusNanos(1), until.plusNanos(1)}) {
      var service = new PromoService(null, Clock.fixed(now, ZoneOffset.UTC));
      assertThatThrownBy(() -> service.validate(promo, false))
          .isInstanceOf(ApiException.class)
          .satisfies(
              ex -> assertThat(((ApiException) ex).code()).isEqualTo(ErrorCode.PROMO_CODE_INVALID));
    }
  }
}
