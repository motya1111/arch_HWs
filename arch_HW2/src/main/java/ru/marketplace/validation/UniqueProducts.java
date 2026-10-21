package ru.marketplace.validation;

import jakarta.validation.Constraint;
import jakarta.validation.Payload;
import java.lang.annotation.*;

@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = UniqueProductsValidator.class)
public @interface UniqueProducts {
  String message() default "product_id values must be unique";

  Class<?>[] groups() default {};

  Class<? extends Payload>[] payload() default {};
}
