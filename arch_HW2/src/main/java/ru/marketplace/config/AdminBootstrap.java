package ru.marketplace.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import ru.marketplace.generated.model.Role;
import ru.marketplace.persistence.MarketplaceRepository;

@Component
@ConditionalOnProperty(name = "marketplace.bootstrap-admin.enabled", havingValue = "true")
public class AdminBootstrap implements ApplicationRunner {
  private final MarketplaceRepository repository;
  private final PasswordEncoder passwords;
  private final String email, password;

  public AdminBootstrap(
      MarketplaceRepository repository,
      PasswordEncoder passwords,
      @Value("${marketplace.bootstrap-admin.email}") String email,
      @Value("${marketplace.bootstrap-admin.password}") String password) {
    this.repository = repository;
    this.passwords = passwords;
    this.email = email;
    this.password = password;
  }

  @Override
  @Transactional
  public void run(ApplicationArguments args) {
    var existing = repository.accountByEmail(email);
    if (existing.isPresent()) {
      if (existing.get().role() != Role.ADMIN)
        throw new IllegalStateException("Bootstrap email belongs to a non-admin user");
      return;
    }
    repository.insertAccount(
        email.toLowerCase(java.util.Locale.ROOT), passwords.encode(password), Role.ADMIN);
  }
}
