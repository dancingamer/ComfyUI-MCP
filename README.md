# ComfyUI MCP

Cursor에서 실행 중인 ComfyUI에 저장된 워크플로우를 지정하고, 그 워크플로우의 체크포인트와 샘플러, 해상도로 프롬프트를 실행합니다. 워크플로우마다 체크포인트가 달라도 같은 방식으로 호출합니다.

`git pull`만으로는 MCP 켜기/끄기 목록에 생기지 않습니다. Cursor는 받은 폴더를 검색해서 MCP를 등록하지 않고, `.cursor/mcp.json`도 자동으로 만들지 않습니다. 켜기/끄기 메뉴는 Cursor로 연 폴더에 그 파일이 있을 때만 나타납니다.

## 사용법

ComfyUI가 `http://127.0.0.1:8188`에서 실행 중이어야 합니다. Cursor에서 ComfyUI 폴더를 연 뒤, 없는 `.cursor/mcp.json`을 직접 만들어 아래 내용을 넣습니다. 파일이 생기면 MCP 목록에 `comfyui` 켜기/끄기가 보입니다.

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "python",
      "args": ["tools/comfyui_mcp/server.py"],
      "env": {
        "COMFYUI_URL": "http://127.0.0.1:8188"
      }
    }
  }
}
```

Cursor에서 MCP 목록을 새로고침하고 `comfyui`를 켭니다.

워크플로우 파일명과 긍정 프롬프트를 지정해 실행합니다. `situations`가 있으면 긍정 프롬프트 뒤에 상황을 순서대로 붙여 한 장씩 대기열에 넣습니다.

```text
workflow: AnimaWorkflows/AnimaV9/AnimaBasicV9.json
positive: 1girl, solo, black dress
situations:
  - sitting in a cafe
  - walking in the rain
```

체크포인트, 샘플러, 해상도는 그 워크플로우 파일에 저장된 값을 사용합니다. 화면의 프롬프트 칸은 바꾸지 않으며, 저장하지 않은 캔버스 수정은 반영되지 않습니다.

사용할 수 있는 기능은 상태 조회, 대기열 조회, 최근 기록, 저장된 워크플로우 목록, 워크플로우 실행, API 그래프 제출, 실행 중단, 대기열 삭제, 메모리 해제입니다.

## 다른 PC에서 받기

ComfyUI 폴더 안에서 이 저장소를 받습니다.

```text
git clone https://github.com/dancingamer/ComfyUI-MCP.git tools/comfyui_mcp
```

Python 3.10 이상이 `python` 명령으로 실행되면 추가 설치는 없습니다. ComfyUI 주소가 다르면 `COMFYUI_URL`을 바꿉니다. 이 폴더가 `ComfyUI/tools/comfyui_mcp`가 아니면 `COMFYUI_ROOT`에 ComfyUI 설치 경로를 넣습니다.
