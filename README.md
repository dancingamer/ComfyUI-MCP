# ComfyUI MCP

Cursor에서 실행 중인 ComfyUI를 직접 다루는 MCP 서버입니다. 상태와 대기열을 읽고, 저장된 워크플로우를 프롬프트만 바꿔 실행하고, 노드와 모델 목록을 조회합니다.

## 연결 구조

ComfyUI를 가져다 쓰지 않고, 이미 떠 있는 서버의 HTTP API를 호출합니다. 별도 의존성이 없고 ComfyUI 코드도 건드리지 않습니다.

```text
Cursor  ──stdio(JSON-RPC)──  server.py  ──HTTP──  ComfyUI (127.0.0.1:8188)
```

주소는 `COMFYUI_URL`로 바꿉니다. 서버가 꺼져 있으면 각 도구가 연결 실패를 그대로 돌려줍니다.

호출하는 ComfyUI 경로는 `/system_stats`, `/queue`, `/history`, `/prompt`, `/interrupt`, `/free`, `/object_info`, `/models`입니다. `comfy_logs`만 LC Vision 커스텀 노드가 더하는 `/lc_vision/translate/logs`를 씁니다.

## 할 수 있는 것

| 도구 | 하는 일 |
|---|---|
| `comfy_status` | 버전, RAM, VRAM, 장치 이름, 실행/대기 개수 |
| `comfy_queue` | 실행 중과 대기 중인 작업의 ID와 노드 수 |
| `comfy_history` | 최근 실행의 상태와 만들어진 파일 이름 |
| `comfy_workflows` | 저장된 워크플로우 목록 (이름으로 거르기) |
| `comfy_run_workflow` | 워크플로우의 체크포인트·샘플러·해상도를 그대로 두고 긍정 프롬프트만 바꿔 실행 |
| `comfy_submit` | API 형식 프롬프트 그래프를 그대로 대기열에 넣기 |
| `comfy_interrupt` | 실행 중단 (`prompt_id`를 주면 그 작업일 때만) |
| `comfy_clear_pending` | 아직 시작하지 않은 대기열 비우기 |
| `comfy_free_memory` | 모델 언로드와 VRAM 해제 |
| `comfy_nodes` | 노드 클래스 목록, 또는 한 노드의 입력과 출력 |
| `comfy_models` | 모델 폴더 목록, 또는 한 폴더의 파일 목록 |
| `comfy_logs` | LC Vision 번역 로그와 진행 여부 |

`comfy_run_workflow`는 화면의 워크플로우를 고치지 않습니다. 저장된 파일을 읽어 API 그래프로 바꾼 뒤 대기열에만 넣으므로, 열어둔 캔버스는 그대로입니다. `situations`를 주면 긍정 프롬프트 뒤에 상황을 하나씩 붙여 그 수만큼 대기열에 넣습니다.

워크플로우에 적힌 체크포인트나 LoRA가 이 PC에 없으면, 그 입력은 설치된 첫 번째 파일로 바뀌어 실행됩니다. 다른 PC에서 만든 워크플로우도 일단 돌아가게 하려는 동작입니다.

`comfy_logs`는 LC Vision이 설치돼 있을 때만 응답합니다. 없으면 404를 그대로 돌려줍니다.

## 설치

ComfyUI가 `http://127.0.0.1:8188`에서 실행 중이어야 합니다.

`git pull`만으로는 MCP 켜기/끄기 목록에 생기지 않습니다. Cursor는 받은 폴더를 검색해서 MCP를 등록하지 않고, `.cursor/mcp.json`도 자동으로 만들지 않습니다. 켜기/끄기 메뉴는 Cursor로 연 폴더에 그 파일이 있을 때만 나타납니다.

Cursor에서 ComfyUI 폴더를 연 뒤 `.cursor/mcp.json`을 직접 만듭니다.

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "python",
      "args": ["tools/comfyui_mcp/server.py"],
      "env": {
        "COMFYUI_URL": "http://127.0.0.1:8188",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

Cursor에서 MCP 목록을 새로고침하고 `comfyui`를 켭니다. `server.py`를 고치면 Cursor를 다시 시작해야 바뀐 도구가 목록에 보입니다.

## 다른 PC에서 받기

ComfyUI 폴더 안에서 이 저장소를 받습니다.

```text
git clone https://github.com/dancingamer/ComfyUI-MCP.git tools/comfyui_mcp
```

Python 3.10 이상이 `python` 명령으로 실행되면 추가 설치는 없습니다.

| 환경변수 | 쓰는 곳 | 기본값 |
|---|---|---|
| `COMFYUI_URL` | 호출할 ComfyUI 주소 | `http://127.0.0.1:8188` |
| `COMFYUI_ROOT` | 이 폴더가 `ComfyUI/tools/comfyui_mcp`가 아닐 때의 설치 경로 | 두 단계 위 폴더 |
| `COMFYUI_WORKFLOWS` | 워크플로우를 찾을 폴더 | `user/default/workflows` |
