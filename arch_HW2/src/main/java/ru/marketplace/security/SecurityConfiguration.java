package ru.marketplace.security;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.*;
import org.springframework.context.annotation.*;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.password.*;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.server.resource.authentication.*;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.*;
import org.springframework.web.filter.OncePerRequestFilter;
import ru.marketplace.error.ErrorWriter;
import ru.marketplace.generated.model.*;
import ru.marketplace.generated.model.Role;

@Configuration
public class SecurityConfiguration {
  public static final String ISSUER = "arch-hw2-marketplace";

  @Bean
  SecretKey signingKey(@Value("${marketplace.jwt-secret}") String secret) {
    if (secret.getBytes(StandardCharsets.UTF_8).length < 32)
      throw new IllegalArgumentException("JWT_SECRET must contain at least 32 UTF-8 bytes");
    return new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
  }

  @Bean
  JwtEncoder jwtEncoder(SecretKey key) {
    return new NimbusJwtEncoder(new ImmutableSecret<>(key));
  }

  @Bean("accessJwtDecoder")
  JwtDecoder accessDecoder(SecretKey key, Clock clock) {
    return decoder(key, clock, "access");
  }

  @Bean("refreshJwtDecoder")
  JwtDecoder refreshDecoder(SecretKey key, Clock clock) {
    return decoder(key, clock, "refresh");
  }

  private JwtDecoder decoder(SecretKey key, Clock clock, String expectedType) {
    var decoder = NimbusJwtDecoder.withSecretKey(key).macAlgorithm(MacAlgorithm.HS256).build();
    var timestamp = new JwtTimestampValidator(Duration.ZERO);
    timestamp.setClock(clock);
    OAuth2TokenValidator<Jwt> claims =
        jwt -> {
          try {
            UUID.fromString(jwt.getSubject());
            UUID.fromString(jwt.getId());
            Role.fromValue(jwt.getClaimAsString("role"));
            if (!expectedType.equals(jwt.getClaimAsString("token_type"))
                || jwt.getExpiresAt() == null
                || jwt.getIssuedAt() == null) throw new IllegalArgumentException();
            return OAuth2TokenValidatorResult.success();
          } catch (Exception ex) {
            return OAuth2TokenValidatorResult.failure(
                new OAuth2Error("invalid_token", "Invalid required claims", null));
          }
        };
    decoder.setJwtValidator(
        new DelegatingOAuth2TokenValidator<>(timestamp, new JwtIssuerValidator(ISSUER), claims));
    return decoder;
  }

  @Bean
  PasswordEncoder passwordEncoder() {
    return Pbkdf2PasswordEncoder.defaultsForSpringSecurity_v5_8();
  }

  @Bean
  SecurityFilterChain security(
      HttpSecurity http, @Qualifier("accessJwtDecoder") JwtDecoder decoder, ErrorWriter errors)
      throws Exception {
    AuthenticationEntryPoint entry =
        (request, response, exception) -> {
          boolean expired = false;
          for (Throwable cause = exception; cause != null; cause = cause.getCause()) {
            if (cause instanceof JwtValidationException validation
                && validation.getErrors().stream()
                    .anyMatch(
                        e ->
                            e.getDescription() != null
                                && e.getDescription().toLowerCase(Locale.ROOT).contains("expired")))
              expired = true;
          }
          errors.write(
              response,
              401,
              expired ? ErrorCode.TOKEN_EXPIRED : ErrorCode.TOKEN_INVALID,
              expired ? "Access token expired" : "Valid access token required");
        };
    var converter = new JwtAuthenticationConverter();
    converter.setJwtGrantedAuthoritiesConverter(
        jwt ->
            List.of(
                new org.springframework.security.core.authority.SimpleGrantedAuthority(
                    "ROLE_" + jwt.getClaimAsString("role"))));
    http.csrf(c -> c.disable())
        .requestCache(c -> c.disable())
        .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .authorizeHttpRequests(
            a ->
                a.requestMatchers(
                        "/auth/**",
                        "/health",
                        "/openapi/**",
                        "/swagger-ui/**",
                        "/swagger-ui.html",
                        "/v3/api-docs/**",
                        "/error")
                    .permitAll()
                    .requestMatchers(HttpMethod.GET, "/products", "/products/**")
                    .hasAnyRole("USER", "SELLER", "ADMIN")
                    .requestMatchers(HttpMethod.POST, "/products")
                    .hasAnyRole("SELLER", "ADMIN")
                    .requestMatchers(HttpMethod.PUT, "/products/*")
                    .hasAnyRole("SELLER", "ADMIN")
                    .requestMatchers(HttpMethod.DELETE, "/products/*")
                    .hasAnyRole("SELLER", "ADMIN")
                    .requestMatchers(HttpMethod.PATCH, "/orders/*/status")
                    .hasRole("ADMIN")
                    .requestMatchers("/orders", "/orders/**")
                    .hasAnyRole("USER", "ADMIN")
                    .requestMatchers(HttpMethod.POST, "/promo-codes")
                    .hasAnyRole("SELLER", "ADMIN")
                    .anyRequest()
                    .authenticated())
        .exceptionHandling(
            e ->
                e.authenticationEntryPoint(entry)
                    .accessDeniedHandler(
                        (q, s, e2) ->
                            errors.write(
                                s, 403, ErrorCode.ACCESS_DENIED, "Insufficient permissions")))
        .oauth2ResourceServer(
            o ->
                o.jwt(j -> j.decoder(decoder).jwtAuthenticationConverter(converter))
                    .authenticationEntryPoint(entry));
    http.addFilterAfter(
        new OncePerRequestFilter() {
          @Override
          protected void doFilterInternal(
              HttpServletRequest request, HttpServletResponse response, FilterChain chain)
              throws ServletException, IOException {
            var authentication =
                org.springframework.security.core.context.SecurityContextHolder.getContext()
                    .getAuthentication();
            if (authentication != null && authentication.getPrincipal() instanceof Jwt jwt)
              request.setAttribute("request_user_id", jwt.getSubject());
            chain.doFilter(request, response);
          }
        },
        BearerTokenAuthenticationFilter.class);
    return http.build();
  }
}
