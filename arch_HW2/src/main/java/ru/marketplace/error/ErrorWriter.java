package ru.marketplace.error;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.stereotype.Component;
import ru.marketplace.generated.model.*;

@Component
public class ErrorWriter {
  private final ObjectMapper mapper;

  public ErrorWriter(ObjectMapper mapper) {
    this.mapper = mapper;
  }

  public static ErrorResponse body(ApiException error) {
    return new ErrorResponse()
        .errorCode(error.code())
        .message(error.getMessage())
        .details(error.details());
  }

  public void write(HttpServletResponse response, int status, ErrorCode code, String message)
      throws IOException {
    response.setStatus(status);
    response.setContentType("application/json");
    response.setCharacterEncoding("UTF-8");
    mapper.writeValue(
        response.getOutputStream(), new ErrorResponse().errorCode(code).message(message));
  }
}
