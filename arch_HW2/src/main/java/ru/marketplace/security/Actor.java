package ru.marketplace.security;

import java.util.UUID;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import ru.marketplace.generated.model.Role;

public record Actor(UUID id, Role role) {
  public static Actor current() {
    var jwt = (Jwt) SecurityContextHolder.getContext().getAuthentication().getPrincipal();
    return new Actor(
        UUID.fromString(jwt.getSubject()), Role.fromValue(jwt.getClaimAsString("role")));
  }

  public boolean admin() {
    return role == Role.ADMIN;
  }
}
