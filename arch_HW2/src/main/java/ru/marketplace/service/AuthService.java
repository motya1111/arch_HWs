package ru.marketplace.service;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.marketplace.error.ApiException;
import ru.marketplace.generated.model.*;
import ru.marketplace.persistence.MarketplaceRepository;
import ru.marketplace.persistence.MarketplaceRepository.Account;
import ru.marketplace.security.SecurityConfiguration;

@Service
public class AuthService {
  private final MarketplaceRepository repository;
  private final PasswordEncoder passwords;
  private final JwtEncoder encoder;
  private final JwtDecoder refreshDecoder;
  private final Clock clock;
  private final long accessMinutes, refreshDays;
  private final String dummyHash;

  public AuthService(
      MarketplaceRepository repository,
      PasswordEncoder passwords,
      JwtEncoder encoder,
      @Qualifier("refreshJwtDecoder") JwtDecoder refreshDecoder,
      Clock clock,
      @Value("${marketplace.access-token-minutes}") long accessMinutes,
      @Value("${marketplace.refresh-token-days}") long refreshDays) {
    if (accessMinutes < 15 || accessMinutes > 30 || refreshDays < 7 || refreshDays > 30)
      throw new IllegalArgumentException("Token lifetimes outside assignment limits");
    this.repository = repository;
    this.passwords = passwords;
    this.encoder = encoder;
    this.refreshDecoder = refreshDecoder;
    this.clock = clock;
    this.accessMinutes = accessMinutes;
    this.refreshDays = refreshDays;
    this.dummyHash = passwords.encode(UUID.randomUUID().toString());
  }

  @Transactional
  public UserResponse register(UserRegister request) {
    try {
      return repository
          .insertAccount(
              request.getEmail().toLowerCase(Locale.ROOT),
              passwords.encode(request.getPassword()),
              Role.fromValue(request.getRole().getValue()))
          .response();
    } catch (DuplicateKeyException ex) {
      throw new ApiException(409, ErrorCode.EMAIL_ALREADY_EXISTS, "Email is already registered");
    }
  }

  @Transactional
  public TokenResponse login(LoginRequest request) {
    var account = repository.accountByEmail(request.getEmail());
    boolean matches =
        passwords.matches(
            request.getPassword(), account.map(Account::passwordHash).orElse(dummyHash));
    if (account.isEmpty() || !matches)
      throw new ApiException(401, ErrorCode.INVALID_CREDENTIALS, "Invalid email or password");
    return issue(account.get());
  }

  @Transactional
  public TokenResponse refresh(RefreshRequest request) {
    Jwt jwt;
    try {
      jwt = refreshDecoder.decode(request.getRefreshToken());
    } catch (JwtException | IllegalArgumentException ex) {
      throw invalidRefresh();
    }
    UUID tokenId = UUID.fromString(jwt.getId());
    var stored = repository.lockRefresh(tokenId).orElseThrow(AuthService::invalidRefresh);
    if (stored.revokedAt() != null
        || !clock.instant().isBefore(stored.expiresAt())
        || !stored.userId().toString().equals(jwt.getSubject())
        || !MessageDigest.isEqual(
            hash(request.getRefreshToken()).getBytes(StandardCharsets.US_ASCII),
            stored.tokenHash().getBytes(StandardCharsets.US_ASCII))) throw invalidRefresh();
    var account =
        repository
            .accountById(UUID.fromString(jwt.getSubject()))
            .orElseThrow(AuthService::invalidRefresh);
    repository.revokeRefresh(tokenId, clock.instant());
    return issue(account);
  }

  private TokenResponse issue(Account account) {
    Instant now = clock.instant();
    UUID refreshId = UUID.randomUUID();
    Instant refreshExpiry = now.plus(Duration.ofDays(refreshDays));
    String refresh = encode(account, refreshId, "refresh", now, refreshExpiry);
    repository.insertRefresh(refreshId, account.id(), hash(refresh), refreshExpiry);
    return new TokenResponse()
        .accessToken(
            encode(
                account,
                UUID.randomUUID(),
                "access",
                now,
                now.plus(Duration.ofMinutes(accessMinutes))))
        .refreshToken(refresh)
        .tokenType(TokenResponse.TokenTypeEnum.BEARER)
        .expiresIn(Math.toIntExact(accessMinutes * 60))
        .user(account.response());
  }

  private String encode(Account account, UUID id, String type, Instant now, Instant expiry) {
    var claims =
        JwtClaimsSet.builder()
            .issuer(SecurityConfiguration.ISSUER)
            .subject(account.id().toString())
            .id(id.toString())
            .issuedAt(now)
            .expiresAt(expiry)
            .claim("role", account.role().getValue())
            .claim("token_type", type)
            .build();
    return encoder
        .encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims))
        .getTokenValue();
  }

  private static String hash(String value) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (NoSuchAlgorithmException ex) {
      throw new IllegalStateException(ex);
    }
  }

  private static ApiException invalidRefresh() {
    return new ApiException(
        401, ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token is invalid, expired or already used");
  }
}
