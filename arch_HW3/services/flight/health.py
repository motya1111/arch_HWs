import os
import grpc
from flights.v1 import flight_pb2 as pb, flight_pb2_grpc as rpc

with grpc.insecure_channel("localhost:50051") as channel:
    response = rpc.FlightServiceStub(channel).Health(
        pb.HealthRequest(),
        metadata=[("x-api-key", os.environ["GRPC_API_KEY"])],
        timeout=2,
    )
    if not response.database_ok:
        raise SystemExit(1)
