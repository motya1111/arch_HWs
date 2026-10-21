package ru.marketplace.error;

import java.util.Map;
import ru.marketplace.generated.model.ErrorCode;

public class ApiException extends RuntimeException {
  private final int status;
  private final ErrorCode code;
  private final Map<String, Object> details;

  public ApiException(int status, ErrorCode code, String message) {
    this(status, code, message, null);
  }

  public ApiException(int status, ErrorCode code, String message, Map<String, Object> details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  public int status() {
    return status;
  }

  public ErrorCode code() {
    return code;
  }

  public Map<String, Object> details() {
    return details;
  }

  public static ApiException validation(String field, String message) {
    return new ApiException(
        400,
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        Map.of("violations", java.util.List.of(Map.of("field", field, "message", message))));
  }
}
