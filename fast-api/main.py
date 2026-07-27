from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ollama
import os
import subprocess
import re
import json
from typing import List, Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_BASE = os.path.join(BASE_DIR, "workdir")
LOGS_BASE = os.path.join(BASE_DIR, "logs")

def get_project_dirs(project_name: str):
    if not project_name or ".." in project_name or "/" in project_name:
        raise HTTPException(status_code=400, detail="Invalid project name")
    
    work_dir = os.path.join(WORKSPACE_BASE, project_name)
    logs_dir = os.path.join(LOGS_BASE, project_name)
    
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    
    if not os.path.exists(os.path.join(work_dir, ".git")):
        subprocess.run(["git", "init"], cwd=work_dir)
        subprocess.run(["git", "config", "user.email", "agent@localhost"], cwd=work_dir)
        subprocess.run(["git", "config", "user.name", "Coding Agent"], cwd=work_dir)
        
    return work_dir, logs_dir

class ChatRequest(BaseModel):
    model: str
    message: str
    project_name: str
    system_prompt: str = ""

@app.get("/models")
async def get_models():
    try:
        response = ollama.list()
        # The ollama python library returns an object with a 'models' attribute containing Model objects
        if hasattr(response, 'models'):
            model_names = [m.model for m in response.models]
        else:
            # Fallback for older library versions
            model_names = [m.get('name') or m.get('model') for m in response.get('models', [])]
        return {"models": model_names}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files")
async def list_files(project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        files = []
        for root, _, filenames in os.walk(work_dir):
            for filename in filenames:
                if '.git' in root:
                    continue
                rel_dir = os.path.relpath(root, work_dir)
                if rel_dir == ".":
                    files.append(filename)
                else:
                    files.append(os.path.join(rel_dir, filename))
        return {"files": files}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files/{filepath:path}")
async def get_file(filepath: str, project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        full_path = os.path.abspath(os.path.join(work_dir, filepath))
        if not full_path.startswith(work_dir):
            raise HTTPException(status_code=403, detail="Access denied")
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/diff")
async def get_diff(project_name: str):
    try:
        work_dir, _ = get_project_dirs(project_name)
        subprocess.run(["git", "add", "."], cwd=work_dir)
        result = subprocess.run(["git", "diff", "--cached"], cwd=work_dir, capture_output=True, text=True)
        return {"diff": result.stdout}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/commit")
async def commit_changes(request: Request):
    try:
        data = await request.json()
        project_name = data.get("project_name")
        work_dir, _ = get_project_dirs(project_name)
        subprocess.run(["git", "add", "."], cwd=work_dir)
        subprocess.run(["git", "commit", "-m", "Agent update"], cwd=work_dir)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
async def get_history(project_name: str):
    try:
        _, logs_dir = get_project_dirs(project_name)
        history_file = os.path.join(logs_dir, "chat_history.json")
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                history = json.load(f)
            return {"history": history}
        return {"history": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        work_dir, logs_dir = get_project_dirs(request.project_name)
        history_file = os.path.join(logs_dir, "chat_history.json")
        
        messages = []
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                messages = json.load(f)
                
        system_instruction = (
            "You are an expert coding agent. "
            "When you create or modify files, you MUST use the following XML format:\n"
            "<file path=\"filename.ext\">\n"
            "code content here...\n"
            "</file>\n"
            "Do NOT use markdown code blocks for files you want to save. "
            "Only use the <file> tag format."
            f"{request.system_prompt}"
        )
        
        # Inject system prompt if it's the first interaction, otherwise just append user msg
        if not messages:
            messages.append({"role": "system", "content": system_instruction})
            
        messages.append({"role": "user", "content": request.message})

        response = ollama.chat(model=request.model, messages=messages)

        reply_content = response['message']['content']
        messages.append({"role": "assistant", "content": reply_content})
        
        with open(history_file, "w") as f:
            json.dump(messages, f, indent=2)

        file_pattern = r'<file\s+path="([^"]+)">\s*(.*?)\s*</file>'
        matches = re.finditer(file_pattern, reply_content, re.DOTALL)
        
        saved_files = []
        for match in matches:
            filepath = match.group(1)
            content = match.group(2)
            
            full_path = os.path.abspath(os.path.join(work_dir, filepath))
            if not full_path.startswith(work_dir):
                continue
                
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            saved_files.append(filepath)

        return {
            "reply": reply_content,
            "saved_files": saved_files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
