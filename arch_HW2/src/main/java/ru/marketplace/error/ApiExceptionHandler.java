package ru.marketplace.error;

import com.fasterxml.jackson.databind.JsonMappingException;
import com.fasterxml.jackson.databind.exc.MismatchedInputException;
import com.fasterxml.jackson.databind.exc.UnrecognizedPropertyException;
import jakarta.validation.ConstraintViolationException;
import java.util.*;
import org.slf4j.*;
import org.springframework.http.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.*;
import org.springframework.web.bind.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.*;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import ru.marketplace.generated.model.*;
import ru.marketplace.generated.model.ErrorResponse;

@RestControllerAdvice
public class ApiExceptionHandler {
  private static final Logger LOGGER = LoggerFactory.getLogger(ApiExceptionHandler.class);

  @InitBinder
  public void strictUuid(WebDataBinder binder, jakarta.servlet.http.HttpServletRequest request) {
    if (request.getMethod().equals("GET") && request.getRequestURI().equals("/products")) {
      for (String field : List.of("page", "size", "status", "category")) {
        String value = request.getParameter(field);
        if (value != null && value.isEmpty())
          throw ApiException.validation(field, "must not be empty");
      }
    }
    binder.registerCustomEditor(
        UUID.class,
        new java.beans.PropertyEditorSupport() {
          @Override
          public void setAsText(String value) {
            if (!value.matches(
                "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
              throw new IllegalArgumentException("must be a canonical UUID");
            setValue(UUID.fromString(value));
          }
        });
  }

  @ExceptionHandler(ApiException.class)
  ResponseEntity<ErrorResponse> business(ApiException error) {
    var builder = ResponseEntity.status(error.status()).contentType(MediaType.APPLICATION_JSON);
    if (error.status() == 429 && error.details() != null)
      builder.header("Retry-After", error.details().get("retry_after_seconds").toString());
    return builder.body(ErrorWriter.body(error));
  }

  @ExceptionHandler(MethodArgumentNotValidException.class)
  ResponseEntity<ErrorResponse> bodyValidation(MethodArgumentNotValidException error) {
    var violations = new ArrayList<Map<String, String>>();
    error
        .getBindingResult()
        .getFieldErrors()
        .forEach(e -> violations.add(violation(e.getField(), e.getDefaultMessage())));
    error
        .getBindingResult()
        .getGlobalErrors()
        .forEach(e -> violations.add(violation("body", e.getDefaultMessage())));
    return invalid(violations);
  }

  @ExceptionHandler(HandlerMethodValidationException.class)
  ResponseEntity<ErrorResponse> methodValidation(HandlerMethodValidationException error) {
    var violations = new ArrayList<Map<String, String>>();
    error
        .getParameterValidationResults()
        .forEach(
            result ->
                result
                    .getResolvableErrors()
                    .forEach(
                        e ->
                            violations.add(
                                violation(
                                    result.getMethodParameter().getParameterName(),
                                    e.getDefaultMessage()))));
    return invalid(violations);
  }

  @ExceptionHandler(ConstraintViolationException.class)
  ResponseEntity<ErrorResponse> constraintValidation(ConstraintViolationException error) {
    return invalid(
        error.getConstraintViolations().stream()
            .map(v -> violation(v.getPropertyPath().toString(), v.getMessage()))
            .toList());
  }

  @ExceptionHandler(HttpMessageNotReadableException.class)
  ResponseEntity<ErrorResponse> malformed(HttpMessageNotReadableException error) {
    String field = "body";
    String message = "body is required and must contain valid JSON";
    for (Throwable cause = error; cause != null; cause = cause.getCause()) {
      if (cause instanceof UnrecognizedPropertyException)
        message = "field is not allowed by the contract";
      else if (cause instanceof MismatchedInputException mismatch)
        message = expectedType(mismatch.getTargetType());
      if (cause instanceof JsonMappingException mapping && !mapping.getPath().isEmpty()) {
        var path = new StringBuilder();
        for (var part : mapping.getPath()) {
          if (part.getFieldName() != null) {
            if (!path.isEmpty()) path.append('.');
            path.append(part.getFieldName());
          } else if (part.getIndex() >= 0) path.append('[').append(part.getIndex()).append(']');
        }
        field = path.toString();
      }
    }
    return invalid(List.of(violation(field, message)));
  }

  @ExceptionHandler(MethodArgumentTypeMismatchException.class)
  ResponseEntity<ErrorResponse> mismatch(MethodArgumentTypeMismatchException error) {
    return invalid(List.of(violation(error.getName(), expectedType(error.getRequiredType()))));
  }

  private String expectedType(Class<?> type) {
    if (type == null) return "has an invalid value";
    if (type.isEnum()) return "must be one of " + Arrays.toString(type.getEnumConstants());
    if (type == UUID.class) return "must be a canonical UUID";
    if (type == String.class) return "must be a string";
    if (type == Integer.class || type == int.class) return "must be an integer in the 32-bit range";
    if (type == Long.class || type == long.class) return "must be an integer in the 64-bit range";
    if (type == Boolean.class || type == boolean.class) return "must be a boolean";
    if (Number.class.isAssignableFrom(type)) return "must be a number";
    if (type == java.time.OffsetDateTime.class)
      return "must be an RFC 3339 date-time with a timezone";
    if (Collection.class.isAssignableFrom(type) || type.isArray()) return "must be an array";
    return "must be a JSON object";
  }

  @ExceptionHandler(MissingServletRequestParameterException.class)
  ResponseEntity<ErrorResponse> missing(MissingServletRequestParameterException error) {
    return invalid(List.of(violation(error.getParameterName(), "is required")));
  }

  @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
  ResponseEntity<ErrorResponse> contentType(HttpMediaTypeNotSupportedException error) {
    return invalid(List.of(violation("Content-Type", "must be application/json")));
  }

  @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
  ResponseEntity<ErrorResponse> accept(HttpMediaTypeNotAcceptableException error) {
    return invalid(List.of(violation("Accept", "must allow application/json")));
  }

  @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
  ResponseEntity<ErrorResponse> method(HttpRequestMethodNotSupportedException error) {
    return business(
        new ApiException(405, ErrorCode.METHOD_NOT_ALLOWED, "HTTP method is not supported"));
  }

  @ExceptionHandler(NoResourceFoundException.class)
  ResponseEntity<ErrorResponse> route(NoResourceFoundException error) {
    return business(new ApiException(404, ErrorCode.ROUTE_NOT_FOUND, "Route not found"));
  }

  @ExceptionHandler(AccessDeniedException.class)
  ResponseEntity<ErrorResponse> denied(AccessDeniedException error) {
    return business(new ApiException(403, ErrorCode.ACCESS_DENIED, "Insufficient permissions"));
  }

  @ExceptionHandler(Exception.class)
  ResponseEntity<ErrorResponse> unexpected(Exception error) {
    LOGGER.error("Unexpected application error", error);
    return business(new ApiException(500, ErrorCode.INTERNAL_ERROR, "Internal server error"));
  }

  private ResponseEntity<ErrorResponse> invalid(List<Map<String, String>> violations) {
    return business(
        new ApiException(
            400,
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            Map.of("violations", violations)));
  }

  private Map<String, String> violation(String field, String message) {
    String snake =
        (field == null ? "request" : field)
            .replaceAll("([a-z0-9])([A-Z])", "$1_$2")
            .toLowerCase(Locale.ROOT);
    return Map.of("field", snake, "message", message == null ? "invalid value" : message);
  }
}
