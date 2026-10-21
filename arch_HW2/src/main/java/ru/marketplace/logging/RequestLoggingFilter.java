package ru.marketplace.logging;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;
import org.slf4j.*;
import org.springframework.core.*;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestLoggingFilter extends OncePerRequestFilter {
  private static final Logger LOG = LoggerFactory.getLogger("marketplace.requests");
  private static final int BODY_LIMIT = 1_048_576;
  private final ObjectMapper mapper;

  public RequestLoggingFilter(ObjectMapper mapper) {
    this.mapper = mapper;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest original, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String requestId = UUID.randomUUID().toString();
    original.setAttribute("request_id", requestId);
    response.setHeader("X-Request-Id", requestId);
    Instant timestamp = Instant.now();
    long started = System.nanoTime();
    byte[] body = new byte[0];
    boolean mutating = Set.of("POST", "PUT", "DELETE", "PATCH").contains(original.getMethod());
    try {
      HttpServletRequest request = original;
      if (mutating) {
        body = original.getInputStream().readNBytes(BODY_LIMIT + 1);
        if (body.length > BODY_LIMIT) {
          response.setStatus(400);
          response.setContentType("application/json");
          var error =
              new ru.marketplace.generated.model.ErrorResponse()
                  .errorCode(ru.marketplace.generated.model.ErrorCode.VALIDATION_ERROR)
                  .message("Request body is too large")
                  .details(
                      Map.of(
                          "violations",
                          List.of(
                              Map.of(
                                  "field", "body", "message", "maximum size is 1048576 bytes"))));
          mapper.writeValue(response.getOutputStream(), error);
          return;
        }
        request = new CachedRequest(original, body);
      }
      chain.doFilter(request, response);
    } finally {
      var event = new LinkedHashMap<String, Object>();
      event.put("request_id", requestId);
      event.put("method", original.getMethod());
      event.put("endpoint", original.getRequestURI());
      event.put("status_code", response.getStatus());
      event.put("duration_ms", (System.nanoTime() - started) / 1_000_000.0);
      event.put("user_id", original.getAttribute("request_user_id"));
      event.put("timestamp", timestamp.toString());
      if (mutating) event.put("request_body", safeBody(body));
      LOG.info(mapper.writeValueAsString(event));
    }
  }

  private Object safeBody(byte[] bytes) {
    if (bytes.length == 0) return null;
    if (bytes.length > BODY_LIMIT) return "[body exceeds log limit]";
    try {
      JsonNode node = mapper.readTree(bytes);
      redact(node);
      return node;
    } catch (Exception ex) {
      return "[unparseable body omitted]";
    }
  }

  private void redact(JsonNode node) {
    if (node instanceof ObjectNode object) {
      var names = new ArrayList<String>();
      object.fieldNames().forEachRemaining(names::add);
      for (String name : names) {
        String key = name.toLowerCase(Locale.ROOT);
        if (key.contains("password")
            || key.contains("token")
            || key.contains("secret")
            || key.contains("authorization")
            || key.contains("cookie")) object.put(name, "***");
        else redact(object.get(name));
      }
    } else if (node instanceof ArrayNode array) array.forEach(this::redact);
  }

  private static class CachedRequest extends HttpServletRequestWrapper {
    private final byte[] bytes;

    CachedRequest(HttpServletRequest request, byte[] bytes) {
      super(request);
      this.bytes = bytes;
    }

    @Override
    public ServletInputStream getInputStream() {
      var stream = new ByteArrayInputStream(bytes);
      return new ServletInputStream() {
        @Override
        public int read() {
          return stream.read();
        }

        @Override
        public boolean isFinished() {
          return stream.available() == 0;
        }

        @Override
        public boolean isReady() {
          return true;
        }

        @Override
        public void setReadListener(ReadListener listener) {
          throw new UnsupportedOperationException("Synchronous API only");
        }
      };
    }

    @Override
    public BufferedReader getReader() {
      return new BufferedReader(new InputStreamReader(getInputStream(), StandardCharsets.UTF_8));
    }
  }
}
