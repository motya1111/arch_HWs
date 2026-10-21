package ru.marketplace.api;

import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.RestController;
import ru.marketplace.generated.api.HealthApi;
import ru.marketplace.generated.model.HealthResponse;

@RestController
public class HealthController implements HealthApi {
  private final JdbcTemplate jdbc;

  public HealthController(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @Override
  public ResponseEntity<HealthResponse> health() {
    jdbc.queryForObject("SELECT 1", Integer.class);
    return ResponseEntity.ok(new HealthResponse().status(HealthResponse.StatusEnum.OK));
  }
}
