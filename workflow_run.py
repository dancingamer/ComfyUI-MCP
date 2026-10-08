import json
import os
import random
from pathlib import Path

BYPASS = 4
TEXT_TYPES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "ImpactWildcardProcessor",
    "ImpactWildcardEncode",
}


def comfy_root():
    env = os.environ.get("COMFYUI_ROOT")
    if env:
        return Path(env)
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "main.py").is_file():
        return candidate
    raise FileNotFoundError("COMFYUI_ROOT 환경변수에 ComfyUI 설치 경로를 지정하세요.")


def workflows_root():
    env = os.environ.get("COMFYUI_WORKFLOWS")
    if env:
        return Path(env)
    return comfy_root() / "user" / "default" / "workflows"


def list_workflows(query=""):
    root = workflows_root()
    if not root.is_dir():
        raise FileNotFoundError(root)
    query = query.lower()
    found = []
    for path in root.rglob("*.json"):
        relative = path.relative_to(root).as_posix()
        if query and query not in relative.lower():
            continue
        found.append(relative)
    found.sort()
    return found


def resolve_workflow(name):
    root = workflows_root().resolve()
    raw = Path(name)
    if raw.is_absolute():
        matches = [raw]
    else:
        direct = root / raw
        matches = [direct] if direct.is_file() else list(root.rglob(raw.name))
    files = []
    for path in matches:
        resolved = path.resolve()
        if resolved.is_file() and resolved.is_relative_to(root) and resolved.suffix.lower() == ".json":
            files.append(resolved)
    unique = list(dict.fromkeys(files))
    if not unique:
        raise FileNotFoundError(name)
    if len(unique) > 1:
        shown = ", ".join(path.relative_to(root).as_posix() for path in unique[:8])
        raise RuntimeError(f"같은 이름의 워크플로우가 여러 개입니다: {shown}")
    return unique[0]


def _load_workflow(path):
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in workflow.get("nodes", [])}
    links = {link[0]: list(link) for link in workflow.get("links", [])}
    return nodes, links


def _passthrough(node, output_type, links):
    for item in node.get("inputs") or []:
        if item.get("type") != output_type or not item.get("link"):
            continue
        source = links.get(item["link"])
        if source:
            return source[1], source[2]
    return None


def _resolve_bypass(nodes, links):
    bypassed = {node_id for node_id, node in nodes.items() if node.get("mode") == BYPASS}
    for _ in range(len(nodes) + 1):
        changed = False
        for link in links.values():
            if link[1] not in bypassed:
                continue
            origin = nodes[link[1]]
            outputs = origin.get("outputs") or []
            if link[2] >= len(outputs):
                continue
            source = _passthrough(origin, outputs[link[2]].get("type"), links)
            if source and (link[1], link[2]) != source:
                link[1], link[2] = source
                changed = True
        if not changed:
            break
    return bypassed


def _reachable(nodes, links, output_ids, bypassed):
    pending = list(output_ids)
    seen = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen or node_id in bypassed or node_id not in nodes:
            continue
        seen.add(node_id)
        for item in nodes[node_id].get("inputs") or []:
            link_id = item.get("link")
            if link_id in links:
                pending.append(links[link_id][1])
    return seen


def _upstream(nodes, links, start_id):
    pending = [start_id]
    seen = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        yield nodes[node_id]
        for item in nodes[node_id].get("inputs") or []:
            link_id = item.get("link")
            if link_id in links:
                pending.append(links[link_id][1])


def _is_negative(node):
    title = f"{node.get('title') or ''} {node.get('type') or ''}".lower()
    return any(word in title for word in ("negative", "neg", "네거티브"))


def _text_field(node):
    if node["type"] == "CLIPTextEncodeSDXL":
        return ("text_g", "text_l")
    if node["type"] in ("ImpactWildcardProcessor", "ImpactWildcardEncode"):
        return ("populated_text",)
    return ("text",)


def _samplers(nodes):
    for node in nodes.values():
        if node.get("mode") == BYPASS:
            continue
        names = {item.get("name") for item in node.get("inputs") or []}
        if {"positive", "negative"} <= names:
            yield node


def _input_link(node, name):
    for item in node.get("inputs") or []:
        if item.get("name") == name:
            return item.get("link")
    return None


def _set_text(node, text):
    named = node.setdefault("widgets_values_named", {})
    for field in _text_field(node):
        named[field] = text
        for item in node.get("inputs") or []:
            if item.get("name") == field:
                item["link"] = None


def _assign_texts(nodes, links, positive, negative):
    positive_ids = []
    negative_ids = []
    for sampler in _samplers(nodes):
        for socket, bucket in (("positive", positive_ids), ("negative", negative_ids)):
            link_id = _input_link(sampler, socket)
            if link_id not in links:
                continue
            for node in _upstream(nodes, links, links[link_id][1]):
                if node["type"] not in TEXT_TYPES:
                    continue
                if socket == "positive" and _is_negative(node):
                    continue
                if socket == "negative" and not _is_negative(node) and node["type"] == "CLIPTextEncode":
                    continue
                bucket.append(node["id"])
                break
    if not positive_ids:
        raise RuntimeError("이 워크플로우에서 긍정 프롬프트 노드를 찾지 못했습니다.")
    for node_id in dict.fromkeys(positive_ids):
        _set_text(nodes[node_id], positive)
    if negative is not None:
        for node_id in dict.fromkeys(negative_ids):
            _set_text(nodes[node_id], negative)


def _set_seed(nodes, seed):
    for node in nodes.values():
        if node.get("mode") == BYPASS:
            continue
        if node["type"] in ("SeedNode", "KSampler", "KSamplerAdvanced"):
            node.setdefault("widgets_values_named", {})["seed"] = int(seed)


def _apply_inputs(node, links, spec, seen):
    inputs = {}
    linked_names = set()
    for item in node.get("inputs") or []:
        link_id = item.get("link")
        if link_id not in links:
            continue
        link = links[link_id]
        if link[1] in seen:
            inputs[item["name"]] = [str(link[1]), link[2]]
            linked_names.add(item["name"])
    named = node.get("widgets_values_named") or {}
    values = list(node.get("widgets_values") or [])
    control = {"fixed", "increment", "decrement", "randomize"}
    order = []
    for section in ("required", "optional"):
        for name in (spec.get("input") or {}).get(section) or {}:
            if name not in linked_names:
                order.append(name)
    index = 0
    for name in order:
        if name in named:
            inputs[name] = named[name]
            if index < len(values):
                index += 1
            if index < len(values) and isinstance(values[index], str) and values[index] in control:
                index += 1
            continue
        while index < len(values) and isinstance(values[index], str) and values[index] in control:
            index += 1
        if index < len(values):
            inputs[name] = values[index]
            index += 1
    if node["type"] == "Power Lora Loader (rgthree)":
        for name, value in named.items():
            if name.startswith("lora_") and isinstance(value, dict):
                inputs[name] = value
    return inputs


def build_workflow_prompt(object_info, workflow_name, positive, negative=None, seed=None):
    path = resolve_workflow(workflow_name)
    nodes, links = _load_workflow(path)
    _assign_texts(nodes, links, positive, negative)
    if seed is not None:
        _set_seed(nodes, seed)
    bypassed = _resolve_bypass(nodes, links)
    output_ids = [
        node_id for node_id, node in nodes.items()
        if node.get("mode") != BYPASS and (object_info.get(node["type"]) or {}).get("output_node")
    ]
    if not output_ids:
        raise RuntimeError("실행 결과가 저장되거나 표시되는 노드가 없습니다.")
    seen = _reachable(nodes, links, output_ids, bypassed)
    prompt = {}
    missing = []
    for node_id in sorted(seen):
        node = nodes[node_id]
        spec = object_info.get(node["type"])
        if not spec:
            missing.append(f"{node['type']} 노드를 서버에서 찾지 못했습니다.")
            continue
        inputs = _apply_inputs(node, links, spec, seen)
        for name in (spec.get("input") or {}).get("required") or {}:
            if name not in inputs:
                missing.append(f"#{node_id} {node['type']}.{name}")
        prompt[str(node_id)] = {"class_type": node["type"], "inputs": inputs}
    if missing:
        raise RuntimeError("워크플로우 변환에 필요한 입력이 없습니다: " + ", ".join(missing[:12]))
    return path, prompt


def prompt_texts(positive, situations):
    situations = [str(item).strip() for item in (situations or []) if str(item).strip()]
    if not situations:
        return [positive]
    return [f"{positive.rstrip(' ,')}, {item}" for item in situations]


def new_seed():
    return random.SystemRandom().randrange(1, 2**53)
