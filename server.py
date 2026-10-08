import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from workflow_run import build_workflow_prompt, list_workflows, new_seed, prompt_texts

BASE = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
OBJECT_INFO = None
PROTOCOL = "2024-11-05"
MAX_TEXT = 60000


def object_info():
    global OBJECT_INFO
    if OBJECT_INFO is None:
        status, info = request("GET", "/object_info")
        if status != 200 or not isinstance(info, dict):
            raise ConnectionError(f"노드 정보를 가져오지 못했습니다: {status}")
        OBJECT_INFO = info
    return OBJECT_INFO


def request(method, path, body=None, query=None):
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            if not raw:
                return res.status, None
            return res.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise ConnectionError(f"ComfyUI에 연결하지 못했습니다 ({BASE}): {exc.reason}") from exc


def text_result(value, error=False):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    if len(value) > MAX_TEXT:
        value = value[:MAX_TEXT] + "\n…(잘림)"
    return {"content": [{"type": "text", "text": value}], "isError": error}


def summarize_queue_item(item):
    prompt_id = item[1] if len(item) > 1 else None
    prompt = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
    return {"number": item[0] if item else None, "prompt_id": prompt_id, "nodes": len(prompt)}


def summarize_history(history):
    out = []
    for prompt_id, item in history.items():
        status = item.get("status") or {}
        outputs = []
        for node_id, node_out in (item.get("outputs") or {}).items():
            for kind in ("images", "gifs", "audio"):
                for media in node_out.get(kind) or []:
                    outputs.append({
                        "node": node_id,
                        "filename": media.get("filename"),
                        "subfolder": media.get("subfolder", ""),
                        "type": media.get("type", "output"),
                    })
        out.append({
            "prompt_id": prompt_id,
            "status": status.get("status_str"),
            "completed": status.get("completed"),
            "outputs": outputs,
        })
    return out


def node_names():
    status, info = request("GET", "/object_info")
    if status != 200 or not isinstance(info, dict):
        return text_result({"status": status, "error": info}, error=True)
    return text_result({"count": len(info), "nodes": sorted(info)})


def node_info(class_name):
    status, info = request("GET", "/object_info/" + urllib.parse.quote(class_name))
    if status != 200:
        return text_result({"status": status, "error": info}, error=True)
    node = info.get(class_name, info)
    inputs = node.get("input", {}) if isinstance(node, dict) else {}
    return text_result({
        "class": class_name,
        "display_name": node.get("display_name") if isinstance(node, dict) else None,
        "category": node.get("category") if isinstance(node, dict) else None,
        "output": node.get("output") if isinstance(node, dict) else None,
        "required": list((inputs.get("required") or {})),
        "optional": list((inputs.get("optional") or {})),
    })


TOOLS = [
    {
        "name": "comfy_status",
        "description": "실행 중인 ComfyUI의 버전, 메모리, 장치, 대기열 개수를 반환합니다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfy_queue",
        "description": "실행 중 작업과 대기 작업의 ID와 노드 수를 반환합니다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfy_history",
        "description": "최근 실행 기록의 상태와 출력 파일명을 반환합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "comfy_workflows",
        "description": "ComfyUI에 저장된 워크플로우 목록을 반환합니다. query로 파일명을 걸러낼 수 있습니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
    {
        "name": "comfy_run_workflow",
        "description": "저장된 워크플로우의 체크포인트, 샘플러, 해상도를 유지한 채 긍정 프롬프트만 바꿔 실행합니다. situations를 주면 그 문장 뒤에 상황을 순서대로 붙여 한 장씩 대기열에 넣습니다. 화면의 칸은 바꾸지 않습니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow": {"type": "string"},
                "positive": {"type": "string"},
                "negative": {"type": "string"},
                "seed": {"type": "integer"},
                "situations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["workflow", "positive"],
        },
    },
    {
        "name": "comfy_submit",
        "description": "API 형식 프롬프트 그래프를 실행 중인 ComfyUI 대기열에 넣습니다. UI 워크플로우 JSON은 받지 않습니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "object"},
                "front": {"type": "boolean"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "comfy_interrupt",
        "description": "현재 실행을 중단합니다. prompt_id를 주면 그 작업이 실행 중일 때만 중단합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt_id": {"type": "string"}},
        },
    },
    {
        "name": "comfy_clear_pending",
        "description": "아직 시작하지 않은 대기열 작업을 지웁니다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfy_free_memory",
        "description": "모델 언로드와 VRAM 해제를 실행 중인 ComfyUI에 요청합니다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfy_nodes",
        "description": "노드 클래스 목록을 반환하거나, class_name을 주면 그 노드의 입력과 출력을 반환합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"class_name": {"type": "string"}},
        },
    },
    {
        "name": "comfy_models",
        "description": "모델 폴더 목록 또는 지정한 폴더의 파일 목록을 반환합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}},
        },
    },
]


def call_tool(name, args):
    args = args or {}
    if name == "comfy_status":
        status, stats = request("GET", "/system_stats")
        qstatus, queue = request("GET", "/queue")
        if status != 200:
            return text_result({"status": status, "error": stats}, error=True)
        system = stats.get("system", {})
        devices = stats.get("devices", [])
        device = devices[0] if devices else {}
        return text_result({
            "url": BASE,
            "version": system.get("comfyui_version"),
            "ram_free": system.get("ram_free"),
            "ram_total": system.get("ram_total"),
            "device": device.get("name"),
            "vram_free": device.get("vram_free"),
            "vram_total": device.get("vram_total"),
            "running": len((queue or {}).get("queue_running", [])) if qstatus == 200 else None,
            "pending": len((queue or {}).get("queue_pending", [])) if qstatus == 200 else None,
        })
    if name == "comfy_queue":
        status, queue = request("GET", "/queue")
        if status != 200:
            return text_result({"status": status, "error": queue}, error=True)
        return text_result({
            "running": [summarize_queue_item(item) for item in queue.get("queue_running", [])],
            "pending": [summarize_queue_item(item) for item in queue.get("queue_pending", [])],
        })
    if name == "comfy_history":
        max_items = int(args.get("max_items") or 5)
        max_items = min(max(max_items, 1), 50)
        status, history = request("GET", "/history", query={"max_items": max_items})
        if status != 200 or not isinstance(history, dict):
            return text_result({"status": status, "error": history}, error=True)
        return text_result(summarize_history(history))
    if name == "comfy_workflows":
        found = list_workflows(str(args.get("query") or ""))
        return text_result({"count": len(found), "workflows": found[:200], "truncated": len(found) > 200})
    if name == "comfy_run_workflow":
        workflow = str(args.get("workflow") or "").strip()
        positive = str(args.get("positive") or "").strip()
        if not workflow or not positive:
            return text_result("workflow와 positive가 필요합니다.", error=True)
        texts = prompt_texts(positive, args.get("situations"))
        seed = args.get("seed")
        queued = []
        for index, text in enumerate(texts):
            job_seed = int(seed) + index if seed is not None else new_seed()
            path, prompt = build_workflow_prompt(
                object_info(),
                workflow,
                text,
                args.get("negative"),
                job_seed,
            )
            status, result = request("POST", "/prompt", {"prompt": prompt})
            queued.append({
                "status": status,
                "workflow": path.name,
                "seed": job_seed,
                "positive": text,
                "result": result,
            })
            if status != 200:
                return text_result({"queued": queued}, error=True)
        return text_result({"count": len(queued), "jobs": queued})
    if name == "comfy_submit":
        prompt = args.get("prompt")
        if not isinstance(prompt, dict) or "nodes" in prompt:
            return text_result("prompt는 API 그래프여야 합니다. 예: {\"3\": {\"class_type\": \"KSampler\", \"inputs\": {}}} ", error=True)
        body = {"prompt": prompt}
        if args.get("front"):
            body["front"] = True
        status, result = request("POST", "/prompt", body)
        return text_result({"status": status, "result": result}, error=status != 200)
    if name == "comfy_interrupt":
        body = {"prompt_id": args["prompt_id"]} if args.get("prompt_id") else {}
        status, _ = request("POST", "/interrupt", body)
        return text_result({"status": status}, error=status != 200)
    if name == "comfy_clear_pending":
        status, _ = request("POST", "/queue", {"clear": True})
        return text_result({"status": status}, error=status != 200)
    if name == "comfy_free_memory":
        status, _ = request("POST", "/free", {"unload_models": True, "free_memory": True})
        return text_result({"status": status}, error=status != 200)
    if name == "comfy_nodes":
        class_name = args.get("class_name")
        return node_info(class_name) if class_name else node_names()
    if name == "comfy_models":
        folder = args.get("folder")
        path = "/models/" + urllib.parse.quote(folder) if folder else "/models"
        status, models = request("GET", path)
        if status != 200:
            return text_result({"status": status, "error": models}, error=True)
        if isinstance(models, list) and len(models) > 300:
            return text_result({"folder": folder or "(types)", "count": len(models), "files": models[:300], "truncated": True})
        return text_result({"folder": folder or "(types)", "files": models})
    return text_result(f"없는 도구: {name}", error=True)


def handle(message):
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "comfyui", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        try:
            result = call_tool(params.get("name"), params.get("arguments"))
        except Exception as exc:
            result = text_result(str(exc), error=True)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"없는 메서드: {method}"},
    }


def read_message():
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        length = int(line.split(b":", 1)[1].strip())
        while True:
            header = sys.stdin.buffer.readline()
            if header in (b"\r\n", b"\n", b""):
                break
        return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))
    return json.loads(line.decode("utf-8"))


def write_message(message):
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


def main():
    while True:
        try:
            message = read_message()
        except Exception as exc:
            print(f"comfyui-mcp: 잘못된 메시지: {exc}", file=sys.stderr)
            continue
        if message is None:
            return
        response = handle(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    main()
