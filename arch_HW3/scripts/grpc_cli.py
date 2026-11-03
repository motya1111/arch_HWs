import json
import os
import sys
import grpc
from google.protobuf.json_format import ParseDict, MessageToDict
from flights.v1 import flight_pb2 as pb, flight_pb2_grpc as rpc

REQUESTS = {
    "SearchFlights": pb.SearchFlightsRequest,
    "GetFlight": pb.GetFlightRequest,
    "ReserveSeats": pb.ReserveSeatsRequest,
    "ReleaseReservation": pb.ReleaseReservationRequest,
    "CreateFlight": pb.CreateFlightRequest,
    "UpdateFlight": pb.UpdateFlightRequest,
    "Health": pb.HealthRequest,
}


def main():
    method = sys.argv[1]
    value = json.load(sys.stdin)
    request = ParseDict(value, REQUESTS[method]())
    key = os.getenv("GRPC_API_KEY", "") if "--no-auth" not in sys.argv else ""
    metadata = [("x-api-key", key)] if key else []
    with grpc.insecure_channel(
        os.getenv("FLIGHT_GRPC_TARGET", "localhost:50051")
    ) as channel:
        try:
            result = getattr(rpc.FlightServiceStub(channel), method)(
                request, metadata=metadata, timeout=5
            )
            print(
                json.dumps(
                    MessageToDict(
                        result,
                        preserving_proto_field_name=True,
                        always_print_fields_with_no_presence=True,
                    )
                )
            )
        except grpc.RpcError as exc:
            print(json.dumps({"grpc_code": exc.code().name, "message": exc.details()}))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
