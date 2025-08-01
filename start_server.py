#!/usr/bin/env python3
"""
Simple startup script for the Podcast Admin Dashboard
"""

import uvicorn
from api_server import app

if __name__ == "__main__":
    print("🎙️  Starting Podcast Admin Dashboard...")
    print("📊 Dashboard will be available at: http://localhost:8000")
    print("🔧 API docs available at: http://localhost:8000/docs")
    print("⏹️  Press Ctrl+C to stop the server")
    print()
    
    uvicorn.run(
        "api_server:app", 
        host="0.0.0.0", 
        port=8000,
        reload=True,
        log_level="info"
    ) 