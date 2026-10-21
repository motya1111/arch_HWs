package ru.marketplace.validation;

import jakarta.validation.ConstraintValidator;
import jakarta.validation.ConstraintValidatorContext;
import java.util.HashSet;
import java.util.List;
import java.util.UUID;
import ru.marketplace.generated.model.*;

public class UniqueProductsValidator implements ConstraintValidator<UniqueProducts, Object> {
  @Override
  public boolean isValid(Object value, ConstraintValidatorContext context) {
    List<OrderItemInput> items =
        switch (value) {
          case OrderCreate request -> request.getItems();
          case OrderUpdate request -> request.getItems();
          default -> null;
        };
    if (items == null) return true;
    var ids = new HashSet<UUID>();
    for (var item : items) {
      if (item == null) {
        context.disableDefaultConstraintViolation();
        context
            .buildConstraintViolationWithTemplate("items must not contain null")
            .addPropertyNode("items")
            .addConstraintViolation();
        return false;
      }
      if (item != null && item.getProductId() != null && !ids.add(item.getProductId())) {
        context.disableDefaultConstraintViolation();
        context
            .buildConstraintViolationWithTemplate("product_id values must be unique")
            .addPropertyNode("items")
            .addConstraintViolation();
        return false;
      }
    }
    return true;
  }
}
