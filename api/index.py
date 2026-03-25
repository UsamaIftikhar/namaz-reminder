# api/index.py
def handler(request):
    # Vercel serverless function equivalent of BaseHTTPRequestHandler
    return "Hello, world!", 200, {"Content-Type": "text/plain"}