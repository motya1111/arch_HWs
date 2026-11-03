from pathlib import Path
import os
from grpc_tools import protoc
import grpc_tools

root = Path(os.getenv("SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
(root / "generated").mkdir(exist_ok=True)
result = protoc.main(
    [
        "protoc",
        f"-I{root / 'contracts'}",
        f"-I{Path(grpc_tools.__file__).parent / '_proto'}",
        f"--python_out={root / 'generated'}",
        f"--grpc_python_out={root / 'generated'}",
        str(root / "contracts/flights/v1/flight.proto"),
    ]
)
if result:
    raise SystemExit(result)
print("Generated protobuf messages, gRPC stub and server base in generated/")
