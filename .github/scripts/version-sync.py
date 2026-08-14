#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING_FILE = REPO_ROOT / "version-mapping.json"

SCHEMA_TEMPLATE = {
    "description": "版本映射配置文件 - 用于管理上游版本与 NAD 版本的对应关系",
    "version_mappings": {},
    "sync_history": [],
    "last_sync": {
        "timestamp": "",
        "upstream_version": "",
        "nad_version": "",
        "trigger_type": ""
    }
}

MAX_HISTORY = 20


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(SCHEMA_TEMPLATE)
    # Preserve description if provided
    if "description" in raw:
        data["description"] = raw["description"]

    data["version_mappings"] = dict(raw.get("version_mappings", {}))

    history = raw.get("sync_history", [])
    if isinstance(history, list):
        data["sync_history"] = history[-MAX_HISTORY:]
    else:
        data["sync_history"] = []

    last_sync = raw.get("last_sync", {})
    if isinstance(last_sync, dict):
        data["last_sync"] = {
            "timestamp": last_sync.get("timestamp", ""),
            "upstream_version": last_sync.get("upstream_version", ""),
            "nad_version": last_sync.get("nad_version", ""),
            "trigger_type": last_sync.get("trigger_type", "")
        }

    return data


def load_version_mapping() -> Dict[str, Any]:
    if not MAPPING_FILE.exists():
        print(f"版本映射文件不存在，正在创建: {MAPPING_FILE}")
        return dict(SCHEMA_TEMPLATE)

    try:
        with MAPPING_FILE.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return _ensure_schema(raw)
    except Exception as exc:
        print(f"加载版本映射文件失败: {exc}", file=sys.stderr)
        return dict(SCHEMA_TEMPLATE)


def _write_mapping(data: Dict[str, Any]) -> None:
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MAPPING_FILE.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def save_version_mapping(upstream_version: str, nad_version: str, trigger_type: str = "auto") -> None:
    if not upstream_version:
        raise ValueError("缺少上游版本号")
    if not nad_version:
        raise ValueError("缺少 NAD 版本号")

    mapping_data = load_version_mapping()
    mapping_data["version_mappings"][upstream_version] = nad_version

    entry = {
        "timestamp": _now_iso(),
        "upstream_version": upstream_version,
        "nad_version": nad_version,
        "trigger_type": trigger_type or "auto"
    }

    history = [sync for sync in mapping_data.get("sync_history", []) if sync.get("upstream_version") != upstream_version]
    history.append(entry)
    mapping_data["sync_history"] = history[-MAX_HISTORY:]
    mapping_data["last_sync"] = entry

    try:
        _write_mapping(mapping_data)
        print(f"版本映射已更新: 上游 {upstream_version} -> NAD {nad_version} ({entry['trigger_type']})")
    except Exception as exc:
        print(f"保存版本映射失败: {exc}", file=sys.stderr)
        raise


def get_upstream_version() -> str | None:
    try:
        result = subprocess.run(
            [
                "curl",
                "-fsSL",
                "https://api.github.com/repos/obsproject/obs-studio/releases/latest",
                "-H",
                "Accept: application/vnd.github+json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"获取上游版本失败: {exc.stderr}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"获取上游版本时发生错误: {exc}", file=sys.stderr)
        return None

    try:
        release_data = json.loads(result.stdout)
        version = (release_data.get("tag_name") or "").lstrip("v")
        if version:
            print(f"上游最新版本: {version}")
            return version
    except Exception as exc:
        print(f"解析上游版本失败: {exc}", file=sys.stderr)

    return None


def list_mappings() -> None:
    mapping_data = load_version_mapping()
    history: List[Dict[str, Any]] = mapping_data.get("sync_history", [])
    mappings: Dict[str, str] = mapping_data.get("version_mappings", {})

    if not history and not mappings:
        print("暂无版本映射数据。使用 `save-mapping` 命令先创建记录。")
        return

    if history:
        print("版本映射历史（最近记录优先）：")
        for idx, entry in enumerate(reversed(history), 1):
            print(f"  {idx}. {entry['timestamp']} :: {entry['upstream_version']} -> {entry['nad_version']} ({entry['trigger_type']})")

    if mappings:
        print("\n当前映射：")
        for upstream, nad in sorted(mappings.items()):
            suffix_ok = f"{upstream}-no-aja" == nad
            status = "OK" if suffix_ok else "  "
            print(f"  [{status}] {upstream} -> {nad}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="管理上游 OBS 版本与 NAD 版本的映射关系，保持 -no-aja 版本后缀。"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("get-upstream", help="获取上游仓库最新版本")

    save_parser = subparsers.add_parser("save-mapping", help="写入 / 更新版本映射")
    save_parser.add_argument("upstream_version", help="上游版本号（例如 33.0.0）")
    save_parser.add_argument("nad_version", help="NAD 版本号（例如 33.0.0-no-aja）")
    save_parser.add_argument(
        "--trigger-type",
        default="manual",
        help="触发来源标签，默认 manual，可选值如 upstream_release、repository_dispatch 等",
    )

    subparsers.add_parser("list", help="查看当前映射与同步历史")

    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0

    args = parser.parse_args(argv)
    command = args.command

    if command == "get-upstream":
        version = get_upstream_version()
        if version is None:
            return 1
        print(f"上游版本: {version}")
        return 0

    if command == "save-mapping":
        try:
            save_version_mapping(args.upstream_version, args.nad_version, args.trigger_type)
        except Exception as exc:
            print(f"保存映射失败: {exc}", file=sys.stderr)
            return 1
        return 0

    if command == "list":
        list_mappings()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
