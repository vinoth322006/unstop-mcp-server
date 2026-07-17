import argparse
import sys

# Import server and ensure tools are registered
from server import mcp
import tools

def main():
    parser = argparse.ArgumentParser(description="Run the Unstop MCP Server")
    parser.add_argument(
        "--transport", 
        type=str, 
        choices=["stdio", "sse"], 
        default="stdio", 
        help="Transport protocol to use (default: stdio)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="Port to run on when using SSE (default: 8000)"
    )
    
    args = parser.parse_args()
    
    if args.transport == "sse":
        print(f"Starting Unstop MCP Server on port {args.port} using SSE transport...")
    
    # Run the server using FastMCP's built-in run method which automatically handles stdio/sse.
    # Note: FastMCP handles stdio transparently if requested.
    mcp.run(transport=args.transport)

if __name__ == "__main__":
    main()
