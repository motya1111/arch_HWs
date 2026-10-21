package ru.marketplace.config;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.cfg.*;
import com.fasterxml.jackson.databind.exc.MismatchedInputException;
import com.fasterxml.jackson.databind.module.SimpleModule;
import com.fasterxml.jackson.databind.type.LogicalType;
import java.io.IOException;
import java.math.BigDecimal;
import java.util.UUID;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.*;

@Configuration
public class JsonConfiguration implements WebMvcConfigurer {
  @Bean
  Jackson2ObjectMapperBuilderCustomizer strictContractTypes() {
    return builder ->
        builder.postConfigurer(
            mapper -> {
              for (var input :
                  new CoercionInputShape[] {
                    CoercionInputShape.Integer, CoercionInputShape.Float, CoercionInputShape.Boolean
                  }) {
                mapper
                    .coercionConfigFor(LogicalType.Textual)
                    .setCoercion(input, CoercionAction.Fail);
              }
              mapper
                  .coercionConfigFor(LogicalType.Integer)
                  .setCoercion(CoercionInputShape.String, CoercionAction.Fail);
              mapper
                  .coercionConfigFor(LogicalType.Boolean)
                  .setCoercion(CoercionInputShape.String, CoercionAction.Fail)
                  .setCoercion(CoercionInputShape.Integer, CoercionAction.Fail);
              var module = new SimpleModule();
              module.addDeserializer(
                  BigDecimal.class,
                  new JsonDeserializer<>() {
                    @Override
                    public BigDecimal deserialize(JsonParser parser, DeserializationContext context)
                        throws IOException {
                      if (parser.currentToken() != JsonToken.VALUE_NUMBER_INT
                          && parser.currentToken() != JsonToken.VALUE_NUMBER_FLOAT) {
                        throw MismatchedInputException.from(
                            parser, BigDecimal.class, "must be a JSON number");
                      }
                      return parser.getDecimalValue().stripTrailingZeros();
                    }
                  });
              module.addDeserializer(
                  UUID.class,
                  new JsonDeserializer<>() {
                    @Override
                    public UUID deserialize(JsonParser parser, DeserializationContext context)
                        throws IOException {
                      if (parser.currentToken() != JsonToken.VALUE_STRING
                          || !canonicalUuid(parser.getText())) {
                        throw MismatchedInputException.from(
                            parser, UUID.class, "must be a canonical UUID");
                      }
                      return UUID.fromString(parser.getText());
                    }
                  });
              mapper.registerModule(module);
            });
  }

  private static boolean canonicalUuid(String value) {
    return value.matches(
        "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
  }

  @Override
  public void addResourceHandlers(ResourceHandlerRegistry registry) {
    registry.addResourceHandler("/openapi/**").addResourceLocations("classpath:/openapi/");
  }
}
