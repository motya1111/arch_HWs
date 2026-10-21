package ru.marketplace.api;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;
import ru.marketplace.generated.api.AuthApi;
import ru.marketplace.generated.model.*;
import ru.marketplace.service.AuthService;

@RestController
public class AuthController implements AuthApi {
  private final AuthService auth;

  public AuthController(AuthService auth) {
    this.auth = auth;
  }

  @Override
  public ResponseEntity<UserResponse> register(UserRegister request) {
    return ResponseEntity.status(201).body(auth.register(request));
  }

  @Override
  public ResponseEntity<TokenResponse> login(LoginRequest request) {
    return ResponseEntity.ok(auth.login(request));
  }

  @Override
  public ResponseEntity<TokenResponse> refresh(RefreshRequest request) {
    return ResponseEntity.ok(auth.refresh(request));
  }
}
